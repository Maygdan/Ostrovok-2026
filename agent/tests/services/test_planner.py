from dataclasses import replace
from datetime import date, timedelta

import pytest

from odin.domain.errors import DomainError, MissingInformation
from odin.domain.junctions import check_plan
from odin.domain.party import Party
from odin.domain.plan import ChangeKind, IssueCode, Severity, Slot, TripPlan
from odin.domain.request import (
    BudgetStyle,
    PatchContext,
    RequestPatch,
    TripRequest,
    apply_patch,
)
from odin.domain.tags import Tag
from odin.domain.transfer import HubKind
from odin.domain.transport import TransportKind
from odin.providers.interfaces import Providers
from odin.providers.mock import build_mock_providers
from odin.services.checkout import CheckoutService
from odin.services.planner import BuildResult, TripPlanner

TODAY = date(2026, 10, 28)
MAIN = {Slot.OUTBOUND, Slot.HOTEL, Slot.INBOUND}
TRANSFERS = {Slot.TRANSFER_IN, Slot.TRANSFER_OUT}


@pytest.fixture(scope="module")
def planner() -> TripPlanner:
    return TripPlanner(build_mock_providers())


def family_request(**fields) -> TripRequest:
    """Семья с ребёнком 7 лет едет на море из Москвы в ноябре, недорого."""
    base = {
        "origin": "moscow",
        "destination": "anapa",
        "month": 11,
        "party": Party(adults=2, children_ages=[7]),
        "tags": [Tag.BEACH],
        "budget_style": BudgetStyle.ECONOMY,
    }
    return TripRequest(**(base | fields))


def change(request: TripRequest, plan: TripPlan | None, **patch) -> TripRequest:
    """Применяет к запросу изменение так же, как это делает инструмент агента."""
    context = PatchContext(
        current_check_in=plan.check_in if plan else None,
        current_total_rub=plan.total_price_rub if plan else None,
    )
    return apply_patch(request, RequestPatch(**patch), context)


def kinds(result: BuildResult) -> dict[Slot, ChangeKind]:
    return {c.slot: c.kind for c in result.diff.changes}


class TestDestinationSearch:
    @pytest.fixture
    def request_(self) -> TripRequest:
        return TripRequest(
            origin="moscow",
            month=9,
            party=Party(adults=2, children_ages=[7]),
            tags=[Tag.BEACH],
            min_sea_temp_c=22,
            min_air_temp_c=22,
            max_travel_hours=5,
            budget_style=BudgetStyle.ECONOMY,
        )

    async def test_warm_sea_in_september_with_short_flights(
        self, planner: TripPlanner, request_: TripRequest
    ) -> None:
        found = await planner.search.destinations(request_, TODAY)

        ranked = [item.option.destination.id for item in found.ranked]
        assert {"anapa", "sochi"} <= set(ranked)
        assert found.window.check_in == date(2027, 9, 10)
        for item in found.ranked:
            facts = item.option
            assert facts.travel_minutes <= 5 * 60
            assert facts.weather.sea_c is not None
            assert facts.weather.sea_c >= 17
            assert facts.price_from_rub > 0
        assert [i.score for i in found.ranked] == sorted(
            (i.score for i in found.ranked), reverse=True
        )

    async def test_every_excluded_destination_says_why(
        self, planner: TripPlanner, request_: TripRequest
    ) -> None:
        found = await planner.search.destinations(request_, TODAY)

        reasons = {e.destination.id: e.reason for e in found.excluded}
        assert "дорога от" in reasons["baikal"]
        assert "купаться нельзя" in reasons["kaliningrad"]
        assert reasons["kazan"] == "нет моря"
        assert set(reasons).isdisjoint(i.option.destination.id for i in found.ranked)
        assert len(reasons) + len(found.ranked) == 10, (
            "каждое направление либо в выдаче, либо с причиной"
        )

    async def test_without_a_sea_wish_cities_are_candidates_too(self, planner: TripPlanner) -> None:
        request = TripRequest(origin="moscow", month=11, tags=[Tag.CITY, Tag.CULTURE])

        found = await planner.search.destinations(request, TODAY)

        assert {"saint-petersburg", "kazan", "kaliningrad"} <= {
            i.option.destination.id for i in found.ranked
        }

    async def test_a_dog_rules_out_destinations_where_no_hotel_takes_dogs(
        self, planner: TripPlanner
    ) -> None:
        request = TripRequest(origin="moscow", month=11, party=Party(adults=2, pets=["dog"]))

        found = await planner.search.destinations(request, TODAY)

        reasons = {e.destination.id: e.reason for e in found.excluded}
        assert "животных" in reasons["kislovodsk"]
        assert "kislovodsk" not in {i.option.destination.id for i in found.ranked}
        assert "anapa" in {i.option.destination.id for i in found.ranked}

    async def test_budget_below_every_trip_leaves_nothing_but_explanations(
        self, planner: TripPlanner
    ) -> None:
        request = family_request(destination=None, budget_total_rub=20_000)

        found = await planner.search.destinations(request, TODAY)

        assert found.ranked == []
        assert any("бюджета" in e.reason for e in found.excluded)

    async def test_departure_city_is_required(self, planner: TripPlanner) -> None:
        with pytest.raises(MissingInformation):
            await planner.search.destinations(TripRequest(month=11), TODAY)


class TestFirstBuild:
    async def test_all_parts_are_chosen_checked_and_explained(self, planner: TripPlanner) -> None:
        result = await planner.build(family_request(), None, TODAY)

        plan = result.plan
        assert plan.missing_slots == []
        assert plan.revision == 1
        assert (plan.check_in, plan.check_out) == (date(2026, 11, 10), date(2026, 11, 17))
        assert plan.errors == []
        assert set(plan.explanations) == set(Slot)
        assert plan.total_price_rub == sum(plan.get(slot).total_price_rub for slot in Slot)
        assert plan.weather is not None
        assert plan.weather.month == 11
        assert {c.kind for c in result.diff.changes} == {ChangeKind.ADDED}
        assert result.recomputed == set(Slot)

    async def test_plan_issues_match_a_fresh_junction_check(self, planner: TripPlanner) -> None:
        plan = (await planner.build(family_request(), None, TODAY)).plan

        assert plan.issues == check_plan(plan)

    async def test_family_choice_is_explained_with_facts_not_slogans(
        self, planner: TripPlanner
    ) -> None:
        plan = (await planner.build(family_request(), None, TODAY)).plan

        hotel = plan.explanations[Slot.HOTEL]
        assert hotel.pros
        assert any("пляж" in note or "бассейн" in note for note in hotel.pros)
        assert plan.explanations[Slot.OUTBOUND].pros

    async def test_transfers_follow_the_flights_and_the_hotel(self, planner: TripPlanner) -> None:
        plan = (await planner.build(family_request(), None, TODAY)).plan

        assert plan.transfer_in.pickup_at >= plan.outbound.arrives_at + plan.outbound.arrival_buffer
        assert (
            plan.transfer_out.arrive_at <= plan.inbound.departs_at - plan.inbound.departure_buffer
        )
        assert plan.transfer_in.hub is HubKind.AIRPORT
        assert (
            plan.hotel.check_in == plan.outbound.arrives_at.astimezone(plan.destination.tz).date()
        )

    async def test_train_trip_uses_station_transfers(self, planner: TripPlanner) -> None:
        request = TripRequest(
            origin="moscow",
            destination="saint-petersburg",
            date_from=date(2026, 11, 13),
            nights=3,
            transport_kinds=[TransportKind.TRAIN],
        )

        plan = (await planner.build(request, None, TODAY)).plan

        assert plan.outbound.kind is TransportKind.TRAIN
        assert plan.inbound.kind is TransportKind.TRAIN
        assert plan.transfer_in.hub is HubKind.STATION
        assert plan.errors == []

    async def test_domestic_trip_has_no_visa_warning(self, planner: TripPlanner) -> None:
        request = TripRequest(
            origin="moscow", destination="sochi", date_from=date(2026, 11, 13), nights=4
        )

        plan = (await planner.build(request, None, TODAY)).plan

        assert not [
            i for i in plan.issues if i.severity is Severity.WARNING and i.code is IssueCode.VISA
        ]

    async def test_destination_is_required(self, planner: TripPlanner) -> None:
        with pytest.raises(MissingInformation):
            await planner.build(family_request(destination=None), None, TODAY)

    async def test_unknown_or_same_city_is_an_error(self, planner: TripPlanner) -> None:
        with pytest.raises(DomainError, match="Неизвестное направление"):
            await planner.build(family_request(destination="atlantis"), None, TODAY)
        with pytest.raises(DomainError, match="совпадают"):
            await planner.build(family_request(origin="kazan", destination="kazan"), None, TODAY)

    async def test_impossible_constraints_explain_what_was_filtered_out(
        self, planner: TripPlanner
    ) -> None:
        with pytest.raises(DomainError) as error:
            await planner.build(family_request(max_travel_hours=1.0), None, TODAY)

        assert "Нет подходящих вариантов" in str(error.value)
        assert "в пути дольше 1 ч" in str(error.value)


class RecordingTransport:
    """Запоминает, на какие даты запрашивали рейсы."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.days: list[date] = []

    async def search(self, origin, destination, day, party):
        self.days.append(day)
        return await self._inner.search(origin, destination, day, party)


class TestTravelTheNightBefore:
    """Дорога, которая не успевает за день, выходит накануне заезда и всё равно прибывает к нему."""

    async def test_overnight_train_is_offered_next_to_the_daytime_one(
        self, planner: TripPlanner
    ) -> None:
        request = TripRequest(
            origin="moscow",
            destination="kazan",
            date_from=date(2026, 11, 14),
            nights=3,
            transport_kinds=[TransportKind.TRAIN],
        )
        trip = await planner.search.resolve_trip(request, TODAY)

        found = await planner.search.transport(trip, Slot.OUTBOUND)

        departures = {item.option.departs_at.date() for item in found.ranked}
        assert departures == {date(2026, 11, 13), date(2026, 11, 14)}
        for item in found.ranked:
            assert (
                item.option.arrives_at.astimezone(trip.destination.tz).date()
                == trip.window.check_in
            )

    async def test_night_train_leaves_the_evening_before_and_the_plan_is_buildable(
        self, planner: TripPlanner
    ) -> None:
        request = TripRequest(
            origin="moscow",
            destination="karelia",
            date_from=date(2026, 11, 10),
            nights=3,
            transport_kinds=[TransportKind.TRAIN],
        )

        plan = (await planner.build(request, None, TODAY)).plan

        assert plan.outbound.departs_at.date() < plan.check_in
        assert plan.outbound.arrives_at.astimezone(plan.destination.tz).date() == plan.check_in
        assert plan.errors == []

    async def test_a_daily_flight_is_offered_on_the_date_that_fits_and_not_twice(
        self, planner: TripPlanner
    ) -> None:
        request = TripRequest(
            origin="moscow", destination="baikal", date_from=date(2026, 11, 10), nights=7
        )
        trip = await planner.search.resolve_trip(request, TODAY)

        found = await planner.search.transport(trip, Slot.OUTBOUND)

        ids = [item.option.id for item in found.ranked]
        assert len(ids) == len(set(ids)) > 1
        assert not {item.option.id for item in found.dropped} & set(ids), (
            "рейс, взятый накануне, не должен числиться отсеянным в день заезда"
        )

    async def test_yesterday_is_never_searched_for_a_departure(self, providers: Providers) -> None:
        recording = RecordingTransport(providers.transport)
        planner = TripPlanner(replace(providers, transport=recording))
        request = TripRequest(
            origin="saint-petersburg", destination="baikal", date_from=TODAY, nights=7
        )

        plan = (await planner.build(request, None, TODAY)).plan

        assert min(recording.days) >= TODAY
        assert plan.outbound.departs_at.date() >= TODAY

    async def test_tomorrows_trip_may_leave_today(self, providers: Providers) -> None:
        recording = RecordingTransport(providers.transport)
        planner = TripPlanner(replace(providers, transport=recording))
        request = TripRequest(
            origin="moscow",
            destination="karelia",
            date_from=TODAY + timedelta(days=1),
            nights=3,
            transport_kinds=[TransportKind.TRAIN],
        )

        plan = (await planner.build(request, None, TODAY)).plan

        assert TODAY in recording.days
        assert plan.outbound.departs_at.date() == TODAY

    async def test_moving_the_dates_of_a_far_trip_keeps_it_buildable(
        self, planner: TripPlanner
    ) -> None:
        request = TripRequest(
            origin="saint-petersburg", destination="baikal", date_from=date(2026, 12, 20), nights=7
        )
        first = await planner.build(request, None, TODAY)

        later = change(request, first.plan, shift_days=3)
        result = await planner.build(later, first.plan, TODAY)

        assert result.plan.check_in == first.plan.check_in + timedelta(days=3)
        assert result.plan.errors == []
        assert result.plan.outbound.arrives_at.date() >= result.plan.check_in

    @pytest.mark.parametrize(
        "origin", ["moscow", "saint-petersburg", "kazan", "yekaterinburg", "novosibirsk"]
    )
    async def test_every_suggested_destination_can_be_arranged(
        self, planner: TripPlanner, origin: str
    ) -> None:
        request = TripRequest(origin=origin, date_from=date(2026, 12, 20), nights=7)
        found = await planner.search.destinations(request, TODAY)

        assert found.ranked
        for item in found.ranked:
            chosen = request.model_copy(update={"destination": item.option.destination.id})
            plan = (await planner.build(chosen, None, TODAY)).plan
            assert plan.errors == [], f"{origin} → {item.option.destination.id}"


class TestRebuild:
    @pytest.fixture
    async def first(self, planner: TripPlanner) -> BuildResult:
        return await planner.build(family_request(), None, TODAY)

    async def test_nothing_changed_nothing_recomputed(
        self, planner: TripPlanner, first: BuildResult
    ) -> None:
        again = await planner.build(first.plan.built_for, first.plan, TODAY)

        assert again.plan is first.plan
        assert again.recomputed == set()
        assert {c.kind for c in again.diff.changes} == {ChangeKind.KEPT}

    async def test_later_dates_keep_the_hotel_and_the_flights_but_move_them(
        self, planner: TripPlanner, first: BuildResult
    ) -> None:
        request = change(first.plan.built_for, first.plan, shift_days=2)

        result = await planner.build(request, first.plan, TODAY)

        old, new = first.plan, result.plan
        assert new.check_in == old.check_in + timedelta(days=2)
        assert new.check_out == old.check_out + timedelta(days=2)
        assert new.hotel.id == old.hotel.id, "тот же отель и тариф"
        assert new.outbound.id == old.outbound.id, "тот же рейс, но на новую дату"
        assert new.outbound.departs_at.date() == old.outbound.departs_at.date() + timedelta(days=2)
        assert new.revision == old.revision + 1
        assert {kinds(result)[slot] for slot in MAIN} <= {ChangeKind.UPDATED, ChangeKind.KEPT}
        assert result.recomputed == set(Slot)
        assert new.errors == []

    async def test_a_dog_changes_only_what_cannot_take_a_dog(
        self, planner: TripPlanner, first: BuildResult
    ) -> None:
        request = change(first.plan.built_for, first.plan, pets=["dog"])

        result = await planner.build(request, first.plan, TODAY)

        plan = result.plan
        assert plan.hotel.hotel.pets_allowed
        assert plan.outbound.pets_allowed
        assert plan.inbound.pets_allowed
        assert plan.transfer_in.pets_allowed
        assert plan.errors == []
        assert kinds(result)[Slot.HOTEL] is ChangeKind.REPLACED
        assert plan.check_in == first.plan.check_in, "даты не тронуты"
        assert plan.destination.id == first.plan.destination.id

    async def test_smaller_budget_swaps_only_what_is_needed(
        self, planner: TripPlanner, first: BuildResult
    ) -> None:
        request = change(first.plan.built_for, first.plan, cheaper_by_percent=10)

        result = await planner.build(request, first.plan, TODAY)

        budget = request.budget_total_rub
        assert budget is not None
        assert result.plan.total_price_rub <= budget
        assert result.plan.total_price_rub < first.plan.total_price_rub
        assert result.plan.errors == []
        assert ChangeKind.KEPT in kinds(result).values(), "не всё пересобрано с нуля"
        assert result.plan.check_in == first.plan.check_in

    async def test_unreachable_budget_is_reported_as_a_blocking_issue(
        self, planner: TripPlanner, first: BuildResult
    ) -> None:
        request = change(first.plan.built_for, first.plan, budget_total_rub=15_000)

        with pytest.raises(DomainError, match="бюджета"):
            await planner.build(request, first.plan, TODAY)

    async def test_hotel_wish_rebuilds_the_hotel_and_its_transfers_only(
        self, planner: TripPlanner, first: BuildResult
    ) -> None:
        request = change(first.plan.built_for, first.plan, min_stars=4)

        result = await planner.build(request, first.plan, TODAY)

        assert result.recomputed == {Slot.HOTEL, *TRANSFERS}
        assert result.plan.hotel.hotel.stars >= 4
        assert result.plan.outbound == first.plan.outbound
        assert result.plan.inbound == first.plan.inbound

    async def test_revision_stays_when_a_rebuild_changes_nothing(
        self, planner: TripPlanner, first: BuildResult
    ) -> None:
        request = change(first.plan.built_for, first.plan, min_stars=first.plan.hotel.hotel.stars)

        result = await planner.build(request, first.plan, TODAY)

        assert result.plan.revision == first.plan.revision
        assert {c.kind for c in result.diff.changes} == {ChangeKind.KEPT}

    async def test_new_destination_replaces_everything_and_the_revision_keeps_growing(
        self, planner: TripPlanner, first: BuildResult
    ) -> None:
        request = change(first.plan.built_for, first.plan, destination="sochi")

        result = await planner.build(request, first.plan, TODAY)

        assert result.plan.destination.id == "sochi"
        assert result.recomputed == set(Slot)
        assert result.plan.revision == first.plan.revision + 1
        assert {c.kind for c in result.diff.changes} == {ChangeKind.REPLACED}
        assert result.diff.price_delta_rub == (
            result.plan.total_price_rub - first.plan.total_price_rub
        )

    async def test_same_offers_that_stopped_fitting_the_budget_are_a_new_revision(
        self, planner: TripPlanner, first: BuildResult
    ) -> None:
        pins = {slot: first.plan.get(slot).id for slot in Slot}
        pinned = await planner.build(first.plan.built_for, first.plan, TODAY, forced=pins)
        tight = change(
            pinned.plan.built_for,
            pinned.plan,
            budget_total_rub=pinned.plan.total_price_rub - 30_000,
        )

        result = await planner.build(tight, pinned.plan, TODAY)

        assert {change.kind for change in result.diff.changes} == {ChangeKind.KEPT}
        assert IssueCode.OVER_BUDGET in {issue.code for issue in result.plan.errors}
        assert result.plan.revision == pinned.plan.revision + 1, "корзина прежней ревизии не верна"


class TestHardWishes:
    async def test_nonstop_only_leaves_direct_flights_in_both_directions(
        self, planner: TripPlanner
    ) -> None:
        request = TripRequest(
            origin="moscow",
            destination="baikal",
            date_from=date(2026, 11, 10),
            nights=7,
            max_stops=0,
        )

        plan = (await planner.build(request, None, TODAY)).plan
        trip = await planner.search.resolve_trip(request, TODAY)
        found = await planner.search.transport(trip, Slot.OUTBOUND)

        assert plan.outbound.stops == 0
        assert plan.inbound.stops == 0
        assert {item.option.stops for item in found.ranked} == {0}
        assert "есть пересадки" in found.reasons

    async def test_nonstop_wish_added_later_replaces_a_connection_and_only_the_roads(
        self, planner: TripPlanner
    ) -> None:
        request = TripRequest(
            origin="moscow",
            destination="baikal",
            date_from=date(2026, 12, 20),
            nights=3,
            budget_style=BudgetStyle.ECONOMY,
            budget_total_rub=92_000,
        )
        first = await planner.build(request, None, TODAY)
        assert first.plan.outbound.stops == 1, "в этом сценарии экономия выбирает пересадку"

        result = await planner.build(change(request, first.plan, max_stops=0), first.plan, TODAY)

        assert result.plan.outbound.stops == 0
        assert result.plan.inbound.stops == 0
        assert kinds(result)[Slot.OUTBOUND] is ChangeKind.REPLACED
        assert kinds(result)[Slot.HOTEL] is ChangeKind.KEPT, "отель желание не затрагивает"
        assert Slot.HOTEL not in result.recomputed

    async def test_free_cancellation_wish_keeps_only_flexible_rates(
        self, planner: TripPlanner
    ) -> None:
        request = TripRequest(
            origin="moscow",
            destination="anapa",
            date_from=date(2026, 12, 20),
            nights=5,
            free_cancellation=True,
        )

        plan = (await planner.build(request, None, TODAY)).plan

        assert plan.hotel.cancellation.refundable


class TestCancellationTerms:
    async def test_free_cancellation_that_has_already_expired_is_not_offered(
        self, planner: TripPlanner
    ) -> None:
        request = TripRequest(
            origin="moscow",
            destination="anapa",
            date_from=TODAY + timedelta(days=2),
            nights=3,
        )
        trip = await planner.search.resolve_trip(request, TODAY)

        found = await planner.search.hotels(trip)

        assert found.ranked
        for item in found.ranked:
            until = item.option.cancellation.free_until
            assert until is None or until >= TODAY, item.option.id

    async def test_the_cart_does_not_promise_a_cancellation_date_in_the_past(
        self, planner: TripPlanner
    ) -> None:
        request = TripRequest(
            origin="moscow",
            destination="anapa",
            date_from=TODAY + timedelta(days=2),
            nights=3,
        )
        flexible = "aaq-dzhemete-family:ai-flex"  # бесплатная отмена за 7 суток до заезда
        plan = (await planner.build(request, None, TODAY, forced={Slot.HOTEL: flexible})).plan

        cart = CheckoutService(build_mock_providers()).create_cart(plan)

        hotel_line = next(item for item in cart.items if item.slot is Slot.HOTEL)
        assert hotel_line.conditions == "невозвратный тариф"


class TestPinnedChoices:
    @pytest.fixture
    async def first(self, planner: TripPlanner) -> BuildResult:
        return await planner.build(family_request(), None, TODAY)

    async def other_hotel(self, planner: TripPlanner, plan: TripPlan) -> str:
        trip = await planner.search.resolve_trip(plan.built_for, TODAY)
        found = await planner.search.hotels(trip)
        return next(r.option.id for r in found.ranked if r.option.hotel.id != plan.hotel.hotel.id)

    async def test_selected_option_replaces_the_choice_and_is_pinned(
        self, planner: TripPlanner, first: BuildResult
    ) -> None:
        wanted = await self.other_hotel(planner, first.plan)

        result = await planner.build(
            first.plan.built_for, first.plan, TODAY, forced={Slot.HOTEL: wanted}
        )

        assert result.plan.hotel.id == wanted
        assert Slot.HOTEL in result.plan.pinned
        assert result.plan.outbound == first.plan.outbound
        assert result.recomputed == {Slot.HOTEL, *TRANSFERS}

    async def test_pinned_hotel_survives_a_date_shift_even_if_not_the_best(
        self, planner: TripPlanner, first: BuildResult
    ) -> None:
        wanted = await self.other_hotel(planner, first.plan)
        pinned = await planner.build(
            first.plan.built_for, first.plan, TODAY, forced={Slot.HOTEL: wanted}
        )

        request = change(pinned.plan.built_for, pinned.plan, shift_days=3)
        shifted = await planner.build(request, pinned.plan, TODAY)

        assert shifted.plan.hotel.id == wanted
        assert Slot.HOTEL in shifted.plan.pinned

    async def test_pinned_hotel_that_sells_out_is_replaced_with_an_explanation(
        self, planner: TripPlanner
    ) -> None:
        request = family_request(date_from=date(2026, 12, 1), nights=4)
        first = await planner.build(request, None, TODAY)
        royal = "aaq-dzhemete-family:ai-flex"
        pinned = await planner.build(request, first.plan, TODAY, forced={Slot.HOTEL: royal})
        assert pinned.plan.hotel.id == royal

        new_year = change(pinned.plan.built_for, pinned.plan, date_from=date(2026, 12, 29))
        result = await planner.build(new_year, pinned.plan, TODAY)

        assert result.plan.hotel.hotel.id != "aaq-dzhemete-family"
        assert Slot.HOTEL not in result.plan.pinned
        assert any("больше недоступен" in note for note in result.notes)

    async def test_pinned_hotel_that_no_longer_fits_the_budget_is_replaced_and_told_why(
        self, planner: TripPlanner
    ) -> None:
        request = family_request(budget_total_rub=250_000)
        first = await planner.build(request, None, TODAY)
        royal = "aaq-dzhemete-family:ai-flex"
        pinned = await planner.build(request, first.plan, TODAY, forced={Slot.HOTEL: royal})
        assert pinned.plan.hotel.id == royal

        tight = change(pinned.plan.built_for, pinned.plan, budget_total_rub=45_000)
        result = await planner.build(tight, pinned.plan, TODAY)

        assert result.plan.hotel.id != royal
        note = next(note for note in result.notes if "выбранный вами вариант" in note)
        assert "дороже всего бюджета" in note
        assert "недоступен" not in note

    async def test_pinned_hotel_that_breaks_the_budget_makes_the_planner_rework_the_rest(
        self, planner: TripPlanner
    ) -> None:
        request = family_request(budget_total_rub=80_000)
        first = await planner.build(request, None, TODAY)
        assert first.plan.errors == []
        sanatorium = "aaq-vityazevo-sanatorium:fb-flex"

        result = await planner.build(request, first.plan, TODAY, forced={Slot.HOTEL: sanatorium})

        assert result.plan.hotel.id == sanatorium
        assert result.plan.errors == [], "бюджет достижим более дешёвыми перелётами и трансферами"
        assert result.plan.total_price_rub <= 80_000
        assert Slot.OUTBOUND in result.recomputed
        assert any("пересмотрены и они" in note for note in result.notes)

    async def test_forced_option_that_breaks_a_hard_rule_is_refused_with_a_reason(
        self, planner: TripPlanner, first: BuildResult
    ) -> None:
        request = change(first.plan.built_for, first.plan, pets=["dog"])

        with pytest.raises(DomainError, match="не принимает животных"):
            await planner.build(
                request, first.plan, TODAY, forced={Slot.HOTEL: "aaq-dzhemete-family:ai-flex"}
            )

    async def test_unknown_option_id_is_refused(
        self, planner: TripPlanner, first: BuildResult
    ) -> None:
        with pytest.raises(DomainError, match="не найден"):
            await planner.build(
                first.plan.built_for, first.plan, TODAY, forced={Slot.HOTEL: "no-such:rate"}
            )

    async def test_selecting_a_transfer_kind(
        self, planner: TripPlanner, first: BuildResult
    ) -> None:
        result = await planner.build(
            first.plan.built_for, first.plan, TODAY, forced={Slot.TRANSFER_IN: "private"}
        )

        assert result.plan.transfer_in.id == "private"
        assert result.plan.transfer_out == first.plan.transfer_out
        assert result.recomputed == {Slot.TRANSFER_IN}
