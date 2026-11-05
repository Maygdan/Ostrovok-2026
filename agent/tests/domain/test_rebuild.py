from datetime import timedelta

import pytest

from odin.domain.dates import DateWindow
from odin.domain.hotel import MealPlan
from odin.domain.plan import ChangeKind, Offer, Slot
from odin.domain.ranking import Ranked
from odin.domain.rebuild import choose, diff_plans, fit_to_budget, stale_slots
from odin.domain.tags import Tag
from tests.factories import (
    CHECK_IN,
    CHECK_OUT,
    MSK,
    at,
    make_flight,
    make_hotel,
    make_hotel_offer,
    make_plan,
    make_request,
    make_transfer,
)

ALL = set(Slot)
MAIN = {Slot.OUTBOUND, Slot.HOTEL, Slot.INBOUND}
TRANSFERS = {Slot.TRANSFER_IN, Slot.TRANSFER_OUT}
WINDOW = DateWindow(CHECK_IN, CHECK_OUT)


def stale_after(**changes) -> set[Slot]:
    """Какие части плана устарели, если запрос изменился так, как описано в `changes`."""
    plan = make_plan()
    request = plan.built_for.model_copy(update=changes)
    return stale_slots(plan, request, WINDOW)


class TestStaleSlots:
    def test_first_build_needs_everything(self) -> None:
        assert stale_slots(None, make_request(), WINDOW) == ALL

    def test_nothing_changed_nothing_to_rebuild(self) -> None:
        assert stale_after() == set()

    def test_comments_and_climate_wishes_do_not_touch_a_built_plan(self) -> None:
        assert stale_after(notes=["не любит жару"], min_sea_temp_c=24) == set()

    def test_shifted_dates_rebuild_the_whole_trip_but_keep_the_destination(self) -> None:
        plan = make_plan()
        later = DateWindow(CHECK_IN + timedelta(days=2), CHECK_OUT + timedelta(days=2))

        assert stale_slots(plan, plan.built_for, later) == ALL

    def test_different_destination_rebuilds_everything(self) -> None:
        plan = make_plan()

        assert stale_slots(plan, make_request(destination="sochi"), WINDOW) == ALL

    def test_a_pet_affects_every_part(self) -> None:
        request = make_request()
        request.party.pets.append("dog")

        assert stale_slots(make_plan(), request, WINDOW) == ALL

    def test_smaller_budget_reprices_main_parts_and_what_depends_on_them(self) -> None:
        assert stale_after(budget_total_rub=100_000) == ALL

    def test_hotel_wishes_rebuild_the_hotel_and_its_transfers_only(self) -> None:
        assert stale_after(min_stars=5) == {Slot.HOTEL, *TRANSFERS}
        assert stale_after(meal_plan=MealPlan.AI) == {Slot.HOTEL, *TRANSFERS}
        assert stale_after(tags=[Tag.SPA]) == {Slot.HOTEL, *TRANSFERS}

    def test_travel_limits_leave_the_hotel_alone(self) -> None:
        assert stale_after(max_travel_hours=3.0) == {Slot.OUTBOUND, Slot.INBOUND, *TRANSFERS}

    def test_origin_change_does_not_touch_the_hotel(self) -> None:
        assert Slot.HOTEL not in stale_after(origin="saint-petersburg")

    def test_missing_parts_are_always_rebuilt_with_their_dependents(self) -> None:
        plan = make_plan(inbound=None)

        assert stale_slots(plan, plan.built_for, WINDOW) == {Slot.INBOUND, Slot.TRANSFER_OUT}


def ranked(offer: Offer, score: float) -> Ranked:
    return Ranked(offer, score)


def hotel(name: str, price: int):
    return make_hotel_offer(hotel=make_hotel(id=name, name=name), price=price, rate_id=name)


class TestChoose:
    @pytest.fixture
    def options(self) -> list[Ranked]:
        return [
            ranked(hotel("best", 90_000), 0.90),
            ranked(hotel("close", 80_000), 0.85),
            ranked(hotel("weak", 50_000), 0.50),
        ]

    def test_without_history_takes_the_best(self, options: list[Ranked]) -> None:
        assert choose(options).option.hotel.id == "best"

    def test_previous_choice_is_kept_if_nearly_as_good(self, options: list[Ranked]) -> None:
        assert choose(options, "close:close").option.hotel.id == "close"

    def test_previous_choice_is_dropped_if_clearly_worse(self, options: list[Ranked]) -> None:
        assert choose(options, "weak:weak").option.hotel.id == "best"

    def test_users_own_choice_survives_while_it_is_still_available(
        self, options: list[Ranked]
    ) -> None:
        assert choose(options, "weak:weak", pinned=True).option.hotel.id == "weak"

    def test_unavailable_previous_choice_falls_back_to_the_best(
        self, options: list[Ranked]
    ) -> None:
        assert choose(options, "gone:gone", pinned=True).option.hotel.id == "best"


class TestFitToBudget:
    @pytest.fixture
    def candidates(self) -> dict[Slot, list[Ranked]]:
        cheap_flight = make_flight(
            at(CHECK_IN, "09:00", MSK), at(CHECK_IN, "12:35"), number="CH1", price=30_000
        )
        flight = make_flight(
            at(CHECK_IN, "08:30", MSK), at(CHECK_IN, "12:05"), number="FL1", price=40_000
        )
        return {
            Slot.HOTEL: [
                ranked(hotel("a", 100_000), 0.90),
                ranked(hotel("b", 80_000), 0.85),
                ranked(hotel("c", 60_000), 0.50),
            ],
            Slot.OUTBOUND: [ranked(flight, 0.90), ranked(cheap_flight, 0.80)],
        }

    @pytest.fixture
    def picks(self, candidates: dict[Slot, list[Ranked]]) -> dict[Slot, Ranked]:
        return {slot: options[0] for slot, options in candidates.items()}

    @staticmethod
    def total(picks: dict[Slot, Ranked]) -> int:
        return sum(p.option.total_price_rub for p in picks.values())

    def test_within_budget_nothing_changes(self, candidates, picks) -> None:
        assert fit_to_budget(candidates, picks, 200_000) == picks

    def test_one_painless_swap_is_enough(self, candidates, picks) -> None:
        fitted = fit_to_budget(candidates, picks, 125_000)

        assert fitted[Slot.HOTEL].option.hotel.id == "b", "наименьшая потеря качества"
        assert fitted[Slot.OUTBOUND] is picks[Slot.OUTBOUND]

    def test_when_no_single_swap_is_enough_several_are_combined(self, candidates, picks) -> None:
        fitted = fit_to_budget(candidates, picks, 95_000)

        assert self.total(fitted) <= 95_000
        assert fitted[Slot.OUTBOUND].option.id == "CH1"

    def test_other_costs_count_towards_the_budget(self, candidates, picks) -> None:
        fitted = fit_to_budget(candidates, picks, 125_000, other_costs_rub=10_000)

        assert self.total(fitted) + 10_000 <= 125_000

    def test_frozen_slots_are_not_touched(self, candidates, picks) -> None:
        fitted = fit_to_budget(candidates, picks, 125_000, frozen={Slot.HOTEL})

        assert fitted[Slot.HOTEL] is picks[Slot.HOTEL]
        assert fitted[Slot.OUTBOUND].option.id == "CH1", "лучшее, что можно сделать без отеля"

    def test_unreachable_budget_returns_the_cheapest_possible_without_looping(
        self, candidates, picks
    ) -> None:
        fitted = fit_to_budget(candidates, picks, 10_000)

        assert fitted[Slot.HOTEL].option.hotel.id == "c"
        assert fitted[Slot.OUTBOUND].option.id == "CH1"


class TestDiffPlans:
    def test_identical_plans_are_all_kept(self) -> None:
        plan = make_plan()

        diff = diff_plans(plan, plan)

        assert {c.kind for c in diff.changes} == {ChangeKind.KEPT}
        assert diff.price_delta_rub == 0

    def test_same_hotel_with_new_price_is_updated(self) -> None:
        before = make_plan()
        after = make_plan(hotel=make_hotel_offer(price=90_000))

        change = next(c for c in diff_plans(before, after).changes if c.slot is Slot.HOTEL)

        assert change.kind is ChangeKind.UPDATED
        assert change.price_delta_rub == 6_000

    def test_different_hotel_is_replaced(self) -> None:
        before = make_plan()
        other = make_hotel_offer(hotel=make_hotel(id="other", name="Other"), price=70_000)

        diff = diff_plans(before, make_plan(hotel=other))

        change = next(c for c in diff.changes if c.slot is Slot.HOTEL)
        assert change.kind is ChangeKind.REPLACED
        assert change.price_delta_rub == -14_000
        assert diff.price_delta_rub == -14_000

    def test_first_build_adds_everything(self) -> None:
        plan = make_plan()

        diff = diff_plans(None, plan)

        assert {c.kind for c in diff.changes} == {ChangeKind.ADDED}
        assert diff.price_delta_rub == plan.total_price_rub

    def test_dropped_part_is_reported_as_removed(self) -> None:
        before = make_plan()
        after = make_plan(transfer_out=None)

        change = next(c for c in diff_plans(before, after).changes if c.slot is Slot.TRANSFER_OUT)

        assert change.kind is ChangeKind.REMOVED
        assert change.price_delta_rub == -before.transfer_out.total_price_rub

    def test_transfer_for_new_flight_time_is_an_update(self) -> None:
        before = make_plan()
        later_pickup = make_transfer(
            before.transfer_in.direction, before.transfer_in.pickup_at + timedelta(hours=1)
        )

        diff = diff_plans(before, make_plan(transfer_in=later_pickup))

        change = next(c for c in diff.changes if c.slot is Slot.TRANSFER_IN)
        assert change.kind is ChangeKind.UPDATED
        assert change.price_delta_rub == 0
