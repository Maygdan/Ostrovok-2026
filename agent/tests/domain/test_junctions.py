from datetime import date, time, timedelta

import pytest

from odin.domain.junctions import arrives_for_check_in, check_plan
from odin.domain.plan import IssueCode, Severity, Slot, TripPlan
from odin.domain.transfer import TransferDirection
from tests.factories import (
    CHECK_IN,
    CHECK_OUT,
    MSK,
    at,
    make_connection,
    make_flight,
    make_hotel,
    make_hotel_offer,
    make_plan,
    make_request,
    make_transfer,
)

IN, OUT = TransferDirection.IN, TransferDirection.OUT


def issues_of(plan: TripPlan) -> dict[IssueCode, Severity]:
    return {issue.code: issue.severity for issue in check_plan(plan)}


def landing_at(arrival: str, day: date = CHECK_IN, pickup: str | None = None) -> dict:
    """Изменения плана: самолёт прилетает в `arrival`, трансфер подан через час после этого."""
    landed = at(day, arrival)
    return {
        "outbound": make_flight(at(day, "05:00", MSK), landed),
        "transfer_in": make_transfer(
            IN, at(day, pickup) if pickup else landed + timedelta(hours=1)
        ),
    }


def test_consistent_plan_has_no_issues() -> None:
    assert check_plan(make_plan()) == []


class TestArrival:
    def test_early_landing_means_long_wait_for_check_in(self) -> None:
        plan = make_plan(**landing_at("06:10"))

        assert issues_of(plan) == {IssueCode.WAIT_FOR_CHECK_IN: Severity.WARNING}

    def test_short_wait_for_check_in_is_fine(self) -> None:
        plan = make_plan(**landing_at("11:00"))

        assert check_plan(plan) == []

    def test_landing_before_check_in_date_is_an_error(self) -> None:
        plan = make_plan(**landing_at("20:00", day=CHECK_IN - timedelta(days=1)))

        assert issues_of(plan)[IssueCode.ARRIVES_BEFORE_CHECK_IN] is Severity.ERROR

    def test_landing_just_after_midnight_is_only_a_warning(self) -> None:
        plan = make_plan(**landing_at("00:40", day=CHECK_IN + timedelta(days=1)))

        assert issues_of(plan) == {IssueCode.LATE_ARRIVAL: Severity.WARNING}

    def test_landing_a_day_later_in_daytime_is_an_error(self) -> None:
        plan = make_plan(**landing_at("10:00", day=CHECK_IN + timedelta(days=1)))

        assert issues_of(plan)[IssueCode.ARRIVES_AFTER_CHECK_IN] is Severity.ERROR

    def test_transfer_booked_before_passengers_leave_terminal(self) -> None:
        plan = make_plan(**landing_at("12:05", pickup="12:30"))

        assert issues_of(plan)[IssueCode.TRANSFER_BEFORE_LANDING] is Severity.ERROR

    def test_transfer_exactly_after_terminal_buffer_is_fine(self) -> None:
        plan = make_plan(**landing_at("12:05", pickup="13:05"))

        assert check_plan(plan) == []

    def test_night_arrival_at_hotel_without_24h_reception(self) -> None:
        hotel = make_hotel_offer(hotel=make_hotel(reception_24h=False))
        plan = make_plan(hotel=hotel, **landing_at("23:00"))

        assert IssueCode.NIGHT_ARRIVAL_AT_HOTEL in issues_of(plan)

    def test_night_arrival_with_24h_reception_is_fine(self) -> None:
        plan = make_plan(**landing_at("22:00"))

        assert IssueCode.NIGHT_ARRIVAL_AT_HOTEL not in issues_of(plan)

    def test_wait_is_measured_against_hotel_check_in_time(self) -> None:
        late_check_in = make_hotel_offer(hotel=make_hotel(check_in_from=time(17, 30)))
        plan = make_plan(hotel=late_check_in)

        assert IssueCode.WAIT_FOR_CHECK_IN in issues_of(plan)


@pytest.mark.parametrize(
    ("day_offset", "clock", "fits"),
    [
        (-1, "20:00", False),  # накануне: нужна лишняя ночь
        (0, "03:30", False),  # ночной прилёт в день заезда: прошлая ночь не оплачена
        (0, "05:59", False),
        (0, "06:00", True),
        (0, "18:30", True),
        (1, "00:40", True),  # после полуночи: приходится на оплаченную ночь заезда
        (1, "05:59", True),
        (1, "06:00", False),  # следующим утром первые ночи оплачены зря
    ],
)
def test_check_in_day_runs_from_morning_to_morning(day_offset: int, clock: str, fits: bool) -> None:
    landed = at(CHECK_IN + timedelta(days=day_offset), clock)

    assert arrives_for_check_in(landed, CHECK_IN) is fits


class TestDeparture:
    def flight_home(self, departs: str, day: date = CHECK_OUT) -> dict:
        return {"inbound": make_flight(at(day, departs), at(day, "23:00", MSK), number="SE414")}

    def test_flight_before_check_out_date_is_an_error(self) -> None:
        plan = make_plan(**self.flight_home("15:40", CHECK_OUT - timedelta(days=1)))

        assert issues_of(plan)[IssueCode.DEPARTS_BEFORE_CHECK_OUT] is Severity.ERROR

    def test_flight_after_check_out_day_leaves_a_night_without_room(self) -> None:
        plan = make_plan(**self.flight_home("14:00", CHECK_OUT + timedelta(days=1)))

        assert issues_of(plan)[IssueCode.DEPARTS_AFTER_CHECK_OUT] is Severity.ERROR

    def test_transfer_that_arrives_too_late_misses_the_flight(self) -> None:
        late_transfer = make_transfer(OUT, at(CHECK_OUT, "12:30"))
        plan = make_plan(transfer_out=late_transfer)

        assert issues_of(plan)[IssueCode.MISSED_DEPARTURE] is Severity.ERROR

    def test_flight_in_the_small_hours_means_night_pickup(self) -> None:
        plan = make_plan(
            **self.flight_home("05:30"),
            transfer_out=make_transfer(OUT, at(CHECK_OUT, "01:30")),
        )

        assert issues_of(plan) == {IssueCode.NIGHT_PICKUP: Severity.WARNING}

    def test_late_evening_flight_means_long_gap_without_room(self) -> None:
        plan = make_plan(
            **self.flight_home("23:50"),
            transfer_out=make_transfer(OUT, at(CHECK_OUT, "19:30")),
        )

        assert issues_of(plan) == {IssueCode.LONG_GAP_AFTER_CHECK_OUT: Severity.WARNING}

    def test_flight_just_after_midnight_is_allowed_but_gap_is_reported(self) -> None:
        plan = make_plan(
            **self.flight_home("01:30", CHECK_OUT + timedelta(days=1)),
            transfer_out=make_transfer(OUT, at(CHECK_OUT, "21:30")),
        )

        assert issues_of(plan) == {IssueCode.LONG_GAP_AFTER_CHECK_OUT: Severity.WARNING}


class TestLayovers:
    def test_short_international_layover_is_risky(self) -> None:
        plan = make_plan(outbound=make_connection(layover_minutes=50))

        assert IssueCode.SHORT_LAYOVER in issues_of(plan)

    def test_comfortable_layover_is_fine(self) -> None:
        plan = make_plan(outbound=make_connection(layover_minutes=120))

        assert IssueCode.SHORT_LAYOVER not in issues_of(plan)
        assert IssueCode.LONG_LAYOVER not in issues_of(plan)

    def test_very_long_layover_is_reported(self) -> None:
        plan = make_plan(outbound=make_connection(layover_minutes=8 * 60))

        assert IssueCode.LONG_LAYOVER in issues_of(plan)


class TestPartyAndBudget:
    def test_hotel_that_rejects_pets_is_an_error(self) -> None:
        request = make_request()
        request.party.pets.append("dog")
        plan = make_plan(built_for=request)

        issues = [i for i in check_plan(plan) if i.code is IssueCode.PETS_NOT_ALLOWED]

        assert Slot.HOTEL in {slot for issue in issues for slot in issue.slots}
        assert all(issue.severity is Severity.ERROR for issue in issues)

    def test_pet_friendly_hotel_and_transfers_are_enough_if_flights_allow_pets(self) -> None:
        request = make_request()
        request.party.pets.append("dog")
        pet_hotel = make_hotel_offer(hotel=make_hotel(pets_allowed=True))
        plan = make_plan(
            built_for=request,
            hotel=pet_hotel,
            outbound=make_flight(
                at(CHECK_IN, "08:30", MSK), at(CHECK_IN, "12:05"), pets_allowed=True
            ),
            inbound=make_flight(
                at(CHECK_OUT, "15:40"),
                at(CHECK_OUT, "21:00", MSK),
                number="SE414",
                pets_allowed=True,
            ),
        )

        assert IssueCode.PETS_NOT_ALLOWED not in issues_of(plan)

    def test_not_enough_room_for_the_party(self) -> None:
        request = make_request()
        request.party.children_ages.extend([3, 6, 9])
        plan = make_plan(built_for=request, hotel=make_hotel_offer(capacity_per_room=3))

        assert issues_of(plan)[IssueCode.NOT_ENOUGH_ROOM] is Severity.ERROR

    def test_total_over_budget_is_an_error(self) -> None:
        plan = make_plan(built_for=make_request(budget_total_rub=100_000))

        assert issues_of(plan) == {IssueCode.OVER_BUDGET: Severity.ERROR}

    def test_total_within_budget_is_fine(self) -> None:
        plan = make_plan(built_for=make_request(budget_total_rub=plan_total()))

        assert check_plan(plan) == []

    def test_hotel_dates_must_match_the_trip(self) -> None:
        shifted = make_hotel_offer(check_in=CHECK_IN + timedelta(days=1))
        plan = make_plan(hotel=shifted)

        assert issues_of(plan)[IssueCode.STAY_MISMATCH] is Severity.ERROR


def plan_total() -> int:
    return make_plan().total_price_rub


@pytest.mark.parametrize(
    ("visa_required", "severity"), [(True, Severity.WARNING), (False, Severity.INFO)]
)
def test_entry_note_is_reported_with_severity_from_visa_requirement(
    visa_required: bool, severity: Severity
) -> None:
    destination = make_plan().destination.model_copy(
        update={"visa_required": visa_required, "entry_note": "Нужна виза"}
    )

    assert issues_of(make_plan(destination=destination)) == {IssueCode.VISA: severity}


def test_checks_skip_parts_that_are_not_planned_yet() -> None:
    plan = make_plan(hotel=None, transfer_in=None, transfer_out=None, inbound=None, outbound=None)

    assert check_plan(plan) == []
