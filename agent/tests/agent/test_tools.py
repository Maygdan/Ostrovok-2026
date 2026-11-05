import json
from typing import Any

import pytest

from odin.agent.llm.types import ToolCall
from odin.agent.session import Session
from odin.agent.tools import default_tools
from odin.agent.tools.base import Tool, ToolArgs, ToolContext, ToolError, ToolRegistry
from odin.domain.errors import DomainError, MissingInformation
from odin.domain.plan import Slot
from tests.agent.conftest import ToolRunner

FAMILY = {
    "month": 11,
    "children_ages": [7],
    "budget_style": "economy",
    "tags": ["beach"],
    "destination": "Анапа",
}


class Boom(ToolArgs):
    kind: str = "crash"


async def boom(ctx: ToolContext, args: Boom) -> dict[str, Any]:
    if args.kind == "domain":
        raise DomainError("Так нельзя")
    if args.kind == "missing":
        raise MissingInformation("Нужны даты")
    if args.kind == "tool":
        raise ToolError("Сначала сделайте другое")
    raise RuntimeError("внутренний сбой, который нельзя показывать")


@pytest.fixture
def risky_registry() -> ToolRegistry:
    return ToolRegistry([Tool("boom", "Падает по-разному", Boom, boom)])


class TestRegistry:
    async def execute(self, registry: ToolRegistry, context: ToolContext, call: ToolCall):
        outcome = await registry.execute(call, context)
        return json.loads(outcome.content), outcome.step

    async def test_unknown_tool_lists_the_available_ones(
        self, registry: ToolRegistry, context: ToolContext
    ) -> None:
        result, step = await self.execute(registry, context, ToolCall.of("fly_to_moon"))

        assert "build_plan" in result["error"]
        assert not step.ok

    async def test_broken_json_is_reported_back_to_the_model(
        self, registry: ToolRegistry, context: ToolContext
    ) -> None:
        call = ToolCall(id="c1", name="search_hotels", arguments="{limit: ")

        result, _ = await self.execute(registry, context, call)

        assert "JSON" in result["error"]

    async def test_non_object_arguments_are_rejected(
        self, registry: ToolRegistry, context: ToolContext
    ) -> None:
        call = ToolCall(id="c1", name="search_hotels", arguments="[1, 2]")

        result, _ = await self.execute(registry, context, call)

        assert "объект" in result["error"]

    async def test_validation_error_names_the_offending_field(
        self, registry: ToolRegistry, context: ToolContext
    ) -> None:
        result, _ = await self.execute(registry, context, ToolCall.of("search_hotels", limit=99))

        assert "limit" in result["error"]

    async def test_unknown_argument_is_rejected_so_the_model_can_fix_it(
        self, registry: ToolRegistry, context: ToolContext
    ) -> None:
        result, _ = await self.execute(
            registry, context, ToolCall.of("update_trip_request", hotel_name="Рога")
        )

        assert "hotel_name" in result["error"]

    async def test_each_failure_kind_becomes_an_error_result(
        self, risky_registry: ToolRegistry, context: ToolContext
    ) -> None:
        domain, _ = await self.execute(risky_registry, context, ToolCall.of("boom", kind="domain"))
        tool, _ = await self.execute(risky_registry, context, ToolCall.of("boom", kind="tool"))
        missing, _ = await self.execute(
            risky_registry, context, ToolCall.of("boom", kind="missing")
        )

        assert domain == {"error": "Так нельзя"}
        assert tool == {"error": "Сначала сделайте другое"}
        assert missing == {"error": "Нужны даты", "ask_user": True}

    async def test_unexpected_crash_does_not_leak_internals_or_stop_the_dialogue(
        self, risky_registry: ToolRegistry, context: ToolContext
    ) -> None:
        result, step = await self.execute(risky_registry, context, ToolCall.of("boom"))

        assert "внутренний сбой" not in json.dumps(result, ensure_ascii=False)
        assert "Внутренняя ошибка" in result["error"]
        assert not step.ok

    async def test_step_records_what_was_called_and_how_it_ended(
        self, registry: ToolRegistry, context: ToolContext
    ) -> None:
        _, step = await self.execute(
            registry, context, ToolCall.of("update_trip_request", month=11)
        )

        assert step.tool == "update_trip_request"
        assert step.arguments == {"month": 11}
        assert step.ok
        assert step.summary.startswith("Запрос обновлён")
        assert step.duration_ms >= 0


class TestSchemas:
    def test_names_are_unique_and_every_tool_is_described(self) -> None:
        tools = default_tools()

        assert len({tool.name for tool in tools}) == len(tools)
        assert all(tool.description for tool in tools)

    def test_parameters_are_flat_provider_friendly_json_schema(self) -> None:
        for tool in default_tools():
            spec = tool.spec()
            text = json.dumps(spec.parameters, ensure_ascii=False)

            assert spec.parameters["type"] == "object", tool.name
            for forbidden in (
                "$ref",
                "$defs",
                '"title"',
                "anyOf",
                "additionalProperties",
                '"format"',
                "exclusiveMinimum",
                "exclusiveMaximum",
            ):
                assert forbidden not in text, (tool.name, forbidden)

    def test_exclusive_integer_bounds_become_inclusive_ones(self) -> None:
        (tool,) = (t for t in default_tools() if t.name == "update_trip_request")
        budget = tool.spec().parameters["properties"]["budget_total_rub"]

        assert budget["minimum"] == 1

    def test_request_tool_exposes_the_vocabulary_the_model_must_use(self) -> None:
        spec = next(t for t in default_tools() if t.name == "update_trip_request").spec()
        properties = spec.parameters["properties"]

        assert "kids_club" in properties["tags"]["items"]["enum"]
        assert properties["budget_style"]["enum"] == ["economy", "standard", "premium"]
        assert "YYYY-MM-DD" in properties["date_from"]["description"]
        assert "shift_days" in properties
        assert "cheaper_by_percent" in properties

    def test_required_arguments_are_marked(self) -> None:
        specs = {t.name: t.spec() for t in default_tools()}

        assert specs["pay_cart"].parameters["required"] == ["confirmed"]
        assert set(specs["select_option"].parameters["required"]) == {"part", "option_id"}


class TestUpdateTripRequest:
    async def test_city_names_are_resolved_to_catalog_ids(
        self, run: ToolRunner, session: Session
    ) -> None:
        result = await run("update_trip_request", destination="в Сочи", origin="из Питера")

        assert "error" not in result
        assert (session.request.origin, session.request.destination) == (
            "saint-petersburg",
            "sochi",
        )

    async def test_naming_the_origin_replaces_the_default_origin_assumption(
        self, run: ToolRunner, session: Session
    ) -> None:
        assert any("по умолчанию" in note for note in session.request.assumptions)

        await run("update_trip_request", origin="из Питера")

        assert session.request.origin == "saint-petersburg"
        assert not any("по умолчанию" in note for note in session.request.assumptions)

    async def test_unknown_destination_names_what_is_available(self, run: ToolRunner) -> None:
        result = await run("update_trip_request", destination="Атлантида")

        assert "Атлантида" in result["error"]
        assert "Анапа" in result["error"]

    async def test_unknown_origin_lists_known_cities(self, run: ToolRunner) -> None:
        result = await run("update_trip_request", origin="Минск")

        assert "Москва" in result["error"]

    async def test_result_reports_what_is_still_missing(self, run: ToolRunner) -> None:
        result = await run("update_trip_request", children_ages=[5])

        assert result["missing"] == ["dates"], "город вылета подставлен по умолчанию"
        assert result["request"]["party_label"] == "2 взрослых + 1 ребёнок (5 лет)"

    async def test_assumptions_and_notes_are_recorded(
        self, run: ToolRunner, session: Session
    ) -> None:
        await run("update_trip_request", assumptions=["Ребёнку 7 лет"], notes=["не любит жару"])

        assert "Ребёнку 7 лет" in session.request.assumptions
        assert any("по умолчанию" in a for a in session.request.assumptions)
        assert session.request.notes == ["не любит жару"]

    async def test_a_limit_can_be_lifted_and_the_plan_follows(
        self, run: ToolRunner, session: Session
    ) -> None:
        await run("update_trip_request", **FAMILY, max_travel_hours=5)
        await run("build_plan")

        result = await run("update_trip_request", clear=["max_travel_hours"])

        assert session.request.max_travel_hours is None
        assert "max_travel_hours" not in result["request"]
        assert set(result["plan_outdated_parts"]) == {
            "outbound",
            "inbound",
            "transfer_in",
            "transfer_out",
        }, "снятый предел времени в пути касается дороги и зависящих от неё трансферов"

    async def test_outdated_assumptions_are_dropped_when_the_model_restates_them(
        self, run: ToolRunner, session: Session
    ) -> None:
        await run("update_trip_request", month=11, assumptions=["7 ночей", "ребёнку 7 лет"])

        await run("update_trip_request", nights=10, assumptions=["ребёнку 7 лет"])

        assert "7 ночей" not in session.request.assumptions
        assert "ребёнку 7 лет" in session.request.assumptions
        assert session.request.assumptions[0].startswith("Вылет из города"), "допущение системы"

    async def test_party_beyond_the_limits_is_an_error_the_model_can_read(
        self, run: ToolRunner, session: Session
    ) -> None:
        result = await run("update_trip_request", children_ages=[1, 2, 3, 4, 5, 6, 7])

        assert "children_ages" in result["error"]
        assert session.request.party.children_ages == []

    async def test_after_a_plan_exists_changes_report_outdated_parts(self, run: ToolRunner) -> None:
        await run("update_trip_request", **FAMILY)
        await run("build_plan")

        result = await run("update_trip_request", pets=["dog"])

        assert set(result["plan_outdated_parts"]) == {s.value for s in Slot}
        assert "build_plan" in result["next"]

    async def test_shift_days_moves_the_dates_of_the_current_plan(
        self, run: ToolRunner, session: Session
    ) -> None:
        await run("update_trip_request", **FAMILY)
        built = await run("build_plan")
        start = built["plan"]["check_in"]

        await run("update_trip_request", shift_days=2)

        assert session.request.date_from is not None
        assert (session.request.date_from - session.plan.check_in).days == 2
        assert start == session.plan.check_in.isoformat()

    async def test_relative_budget_cut_uses_the_plan_total(
        self, run: ToolRunner, session: Session
    ) -> None:
        await run("update_trip_request", **FAMILY)
        await run("build_plan")
        total = session.plan.total_price_rub

        await run("update_trip_request", cheaper_by_percent=10)

        assert session.request.budget_total_rub == round(total * 0.9, -2)

    async def test_contradicting_changes_are_reported(self, run: ToolRunner) -> None:
        result = await run("update_trip_request", shift_days=2, month=12)

        assert "shift_days" in result["error"]


class TestSearchTools:
    async def test_destinations_come_with_reasons_for_rejected_ones(self, run: ToolRunner) -> None:
        await run(
            "update_trip_request",
            month=9,
            children_ages=[7],
            tags=["beach"],
            min_sea_temp_c=22,
            max_travel_hours=5,
        )

        result = await run("search_destinations", limit=2)

        assert len(result["options"]) == 2
        first = result["options"][0]
        assert {"id", "name", "price_from_rub", "weather", "pros"} <= set(first)
        assert any(item["name"] == "Байкал" for item in result["excluded"])

    async def test_empty_destination_search_suggests_relaxing_conditions(
        self, run: ToolRunner
    ) -> None:
        await run("update_trip_request", month=11, budget_total_rub=20_000)

        result = await run("search_destinations")

        assert result["options"] == []
        assert "смягчить" in result["hint"]

    async def test_destination_search_asks_for_missing_dates(self, run: ToolRunner) -> None:
        result = await run("search_destinations")

        assert result["ask_user"] is True

    async def test_hotels_are_compared_with_explanations(self, run: ToolRunner) -> None:
        await run("update_trip_request", **FAMILY)

        result = await run("search_hotels", limit=3)

        assert len(result["options"]) == 3
        assert all("pros" in hotel for hotel in result["options"])
        assert all(hotel["id"].count(":") == 1 for hotel in result["options"])

    async def test_hotels_need_a_destination(self, run: ToolRunner) -> None:
        await run("update_trip_request", month=11)

        result = await run("search_hotels")

        assert result["ask_user"] is True

    async def test_transport_in_both_directions(self, run: ToolRunner) -> None:
        await run("update_trip_request", **FAMILY)

        there = await run("search_transport", direction="outbound")
        back = await run("search_transport", direction="inbound")

        assert there["options"]
        assert back["options"]
        assert there["options"][0]["departs"] < back["options"][0]["departs"]

    async def test_transfers_need_a_plan_first(self, run: ToolRunner) -> None:
        result = await run("search_transfers", direction="in")

        assert "build_plan" in result["error"]

    async def test_transfers_match_the_planned_flight(self, run: ToolRunner) -> None:
        await run("update_trip_request", **FAMILY)
        built = await run("build_plan")

        result = await run("search_transfers", direction="in")

        landing = built["plan"]["outbound"]["arrives"]
        assert result["options"]
        assert all(option["pickup"] >= landing for option in result["options"])


class TestPlanTools:
    async def test_first_build_returns_an_explained_plan_without_a_diff(
        self, run: ToolRunner, session: Session
    ) -> None:
        await run("update_trip_request", **FAMILY)

        result = await run("build_plan")

        plan = result["plan"]
        assert result["ready_for_cart"] is True
        assert "changes" not in result
        assert session.plan is not None
        assert plan["hotel"]["pros"]
        assert plan["destination"]["name"] == "Анапа"
        assert set(result["recomputed_parts"]) == {s.value for s in Slot}

    async def test_build_without_destination_asks_the_user(self, run: ToolRunner) -> None:
        await run("update_trip_request", month=11)

        result = await run("build_plan")

        assert result["ask_user"] is True

    async def test_rebuild_reports_what_changed_part_by_part(self, run: ToolRunner) -> None:
        await run("update_trip_request", **FAMILY)
        await run("build_plan")
        await run("update_trip_request", shift_days=2)

        result = await run("build_plan")

        statuses = {part["part"]: part["status"] for part in result["changes"]["parts"]}
        assert statuses["hotel"] == "updated"
        assert statuses["outbound"] == "updated"
        assert result["plan"]["revision"] == 2

    async def test_selected_option_is_pinned_and_reported_as_users_choice(
        self, run: ToolRunner, session: Session
    ) -> None:
        await run("update_trip_request", **FAMILY)
        built = await run("build_plan")
        hotels = await run("search_hotels", limit=10)
        other = next(h for h in hotels["options"] if h["id"] != built["plan"]["hotel"]["id"])

        result = await run("select_option", part="hotel", option_id=other["id"])

        assert result["plan"]["hotel"]["id"] == other["id"]
        assert result["plan"]["chosen_by_user"] == ["hotel"]
        assert session.plan.hotel.id == other["id"]

    async def test_selecting_an_unknown_option_explains_the_problem(self, run: ToolRunner) -> None:
        await run("update_trip_request", **FAMILY)
        await run("build_plan")

        result = await run("select_option", part="hotel", option_id="nope:nope")

        assert "не найден" in result["error"]

    async def test_select_requires_a_plan(self, run: ToolRunner) -> None:
        result = await run("select_option", part="hotel", option_id="x:y")

        assert "build_plan" in result["error"]

    async def test_check_plan_reports_readiness_and_outdated_parts(self, run: ToolRunner) -> None:
        await run("update_trip_request", **FAMILY)
        await run("build_plan")
        await run("update_trip_request", min_stars=5)

        result = await run("check_plan")

        assert result["ready_for_cart"] is True
        assert set(result["plan_outdated_parts"]) == {"hotel", "transfer_in", "transfer_out"}

    async def test_tools_that_change_the_trip_are_closed_after_the_purchase(
        self, run: ToolRunner, session: Session
    ) -> None:
        await run("update_trip_request", **FAMILY)
        await run("build_plan")
        await run("create_cart")
        session.cart = session.cart.mark_presented()
        await run("pay_cart", confirmed=True)

        for name, arguments in (
            ("update_trip_request", {"shift_days": 1}),
            ("build_plan", {}),
            ("create_cart", {}),
        ):
            result = await run(name, **arguments)
            assert "Заказ уже оформлен" in result["error"], name


class TestCheckoutTools:
    async def build(self, run: ToolRunner) -> None:
        await run("update_trip_request", **FAMILY)
        await run("build_plan")

    async def test_cart_needs_a_plan(self, run: ToolRunner) -> None:
        assert "build_plan" in (await run("create_cart"))["error"]

    async def test_cart_lists_every_part_and_tells_the_model_to_ask_for_confirmation(
        self, run: ToolRunner, session: Session
    ) -> None:
        await self.build(run)

        result = await run("create_cart")

        assert len(result["cart"]["items"]) == 5
        assert result["cart"]["total_price_rub"] == session.plan.total_price_rub
        assert "Не вызывайте pay_cart" in result["next"]
        assert session.cart is not None

    async def test_outdated_plan_cannot_go_to_the_cart(self, run: ToolRunner) -> None:
        await self.build(run)
        await run("update_trip_request", shift_days=1)

        result = await run("create_cart")

        assert "build_plan" in result["error"]

    async def test_payment_requires_explicit_confirmation(self, run: ToolRunner) -> None:
        await self.build(run)
        await run("create_cart")

        result = await run("pay_cart", confirmed=False)

        assert "подтверждения" in result["error"]

    async def test_payment_in_the_same_turn_as_the_cart_is_refused(
        self, run: ToolRunner, session: Session
    ) -> None:
        await self.build(run)
        await run("create_cart")

        result = await run("pay_cart", confirmed=True)

        assert "не видел пользователь" in result["error"]
        assert session.order is None

    async def test_payment_without_a_cart_is_refused(self, run: ToolRunner) -> None:
        assert "create_cart" in (await run("pay_cart", confirmed=True))["error"]

    async def test_confirmed_payment_after_the_cart_was_shown_creates_the_order(
        self, run: ToolRunner, session: Session
    ) -> None:
        await self.build(run)
        await run("create_cart")
        session.cart = session.cart.mark_presented()

        result = await run("pay_cart", confirmed=True)

        assert result["order"]["total_price_rub"] == session.plan.total_price_rub
        assert len(result["order"]["bookings"]) == 5
        assert session.order is not None
        assert session.cart.status.value == "paid"
        assert "имитация" in result["order"]["payment"]["note"]

    async def test_another_destination_throws_the_old_cart_away(
        self, run: ToolRunner, session: Session
    ) -> None:
        await self.build(run)
        await run("create_cart")
        session.cart = session.cart.mark_presented()
        old_revision = session.plan.revision
        await run("update_trip_request", destination="Сочи")

        result = await run("build_plan")

        assert session.plan.revision == old_revision + 1
        assert session.cart is None
        assert any("корзина сброшена" in note.lower() for note in result["notes"])
        assert "build_plan" not in (await run("pay_cart", confirmed=True))["error"]
        assert session.order is None

    @pytest.mark.parametrize(
        "change",
        [{"shift_days": 2, "adults": 4}, {"shift_days": -20}],
        ids=["request changed", "date moved into the past"],
    )
    async def test_cart_is_not_payable_after_the_request_moved_on_without_a_rebuild(
        self, run: ToolRunner, session: Session, change: dict[str, int]
    ) -> None:
        await self.build(run)
        await run("create_cart")
        session.cart = session.cart.mark_presented()
        await run("update_trip_request", **change)

        result = await run("pay_cart", confirmed=True)

        assert "build_plan" in result["error"]
        assert session.order is None

    async def test_replanning_throws_the_old_cart_away(
        self, run: ToolRunner, session: Session
    ) -> None:
        await self.build(run)
        await run("create_cart")
        await run("update_trip_request", shift_days=2)

        result = await run("build_plan")

        assert session.cart is None
        assert any("корзина сброшена" in note.lower() for note in result["notes"])
