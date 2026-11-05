from datetime import date

import pytest
from pydantic import ValidationError

from odin.domain.dates import resolve_window
from odin.domain.errors import DomainError, MissingInformation
from odin.domain.request import (
    BudgetStyle,
    PatchContext,
    RequestPatch,
    TripRequest,
    apply_patch,
)
from odin.domain.tags import Tag

TODAY = date(2026, 10, 28)


def patched(request: TripRequest, context: PatchContext | None = None, **changes) -> TripRequest:
    return apply_patch(request, RequestPatch(**changes), context or PatchContext())


def test_request_reports_what_is_missing_for_search() -> None:
    assert TripRequest().missing == ["origin", "dates"]
    assert TripRequest(origin="moscow", month=11).missing == []


def test_patch_sets_only_provided_fields() -> None:
    request = TripRequest(origin="moscow", month=11, nights=7)

    updated = patched(request, destination="sochi", budget_style="economy")

    assert updated.destination == "sochi"
    assert updated.budget_style is BudgetStyle.ECONOMY
    assert (updated.origin, updated.month, updated.nights) == ("moscow", 11, 7)
    assert request.destination is None, "исходный запрос не должен меняться"


def test_tags_are_merged_and_can_be_dropped() -> None:
    request = TripRequest(tags=[Tag.BEACH, Tag.POOL])

    updated = patched(request, tags=[Tag.POOL, Tag.KIDS_CLUB], drop_tags=[Tag.BEACH])

    assert updated.tags == [Tag.POOL, Tag.KIDS_CLUB]


def test_notes_accumulate_without_duplicates() -> None:
    request = TripRequest(notes=["не любит жару"])

    updated = patched(request, notes=["не любит жару", "боится самолётов"])

    assert updated.notes == ["не любит жару", "боится самолётов"]


def test_assumptions_are_replaced_so_that_outdated_ones_do_not_pile_up() -> None:
    request = TripRequest(assumptions=["7 ночей", "ребёнку 7 лет"])

    updated = patched(request, nights=10, assumptions=["ребёнку 7 лет"])

    assert updated.assumptions == ["ребёнку 7 лет"]
    assert patched(request, nights=10).assumptions == request.assumptions, "не названы — не тронуты"
    assert patched(request, assumptions=[]).assumptions == []


def test_default_origin_assumption_belongs_to_the_system_and_survives_model_updates() -> None:
    note = "Вылет из города Москва — выбран по умолчанию."
    request = TripRequest(origin="moscow", assumptions=[note, "7 ночей"])

    updated = patched(request, assumptions=["ребёнку 7 лет"])

    assert updated.assumptions == [note, "ребёнку 7 лет"]
    assert patched(request, assumptions=[note, "ребёнку 7 лет"]).assumptions == updated.assumptions
    named = patched(request, origin="kazan", assumptions=[note])
    assert named.assumptions == [], "город назван — допущение о нём снимается"


def test_default_origin_assumption_disappears_once_the_user_names_a_city() -> None:
    request = TripRequest(
        origin="moscow",
        assumptions=["Вылет из города Москва — выбран по умолчанию.", "7 ночей"],
    )

    updated = patched(request, origin="saint-petersburg")

    assert updated.assumptions == ["7 ночей"]
    assert patched(request, month=11).assumptions == request.assumptions


LIMITS = {
    "budget_total_rub": 60_000,
    "max_travel_hours": 5.0,
    "min_air_temp_c": 22,
    "min_sea_temp_c": 22,
    "min_stars": 4,
    "meal_plan": "AI",
    "max_stops": 0,
}


def test_limits_can_be_cleared_when_the_user_says_it_does_not_matter() -> None:
    request = patched(TripRequest(), **LIMITS)
    assert request.max_travel_hours == 5.0

    cleared = patched(request, clear=["max_travel_hours", "budget_total_rub", "meal_plan"])

    assert (cleared.max_travel_hours, cleared.budget_total_rub, cleared.meal_plan) == (None,) * 3
    assert (cleared.min_air_temp_c, cleared.min_sea_temp_c, cleared.min_stars) == (22, 22, 4)
    assert request.max_travel_hours == 5.0, "исходный запрос не должен меняться"


@pytest.mark.parametrize("name", LIMITS)
def test_every_limit_is_clearable(name: str) -> None:
    request = patched(TripRequest(), **LIMITS)

    assert getattr(patched(request, clear=[name]), name) is None


def test_nonstop_and_free_cancellation_wishes_can_be_set_and_withdrawn() -> None:
    wished = patched(TripRequest(), max_stops=0, free_cancellation=True)

    assert (wished.max_stops, wished.free_cancellation) == (0, True)
    relaxed = patched(wished, max_stops=1, free_cancellation=False)
    assert (relaxed.max_stops, relaxed.free_cancellation) == (1, False)
    assert patched(wished, clear=["max_stops"]).max_stops is None


def test_party_limits_of_the_model_are_enforced_when_patching() -> None:
    with pytest.raises(ValidationError, match="children_ages"):
        patched(TripRequest(), children_ages=[1, 2, 3, 4, 5, 6, 7])
    with pytest.raises(ValidationError, match="pets"):
        patched(TripRequest(), pets=["dog", "cat", "other", "dog"])


def test_empty_transport_list_is_refused_instead_of_silently_leaving_no_options() -> None:
    with pytest.raises(ValidationError):
        RequestPatch(transport_kinds=[])
    with pytest.raises(ValidationError):
        TripRequest(transport_kinds=[])


def test_party_fields_replace_only_what_is_given() -> None:
    request = TripRequest()
    request.party.children_ages.append(5)

    updated = patched(request, pets=["dog"])

    assert updated.party.children_ages == [5]
    assert updated.party.pets == ["dog"]
    assert updated.party.adults == 2


def test_shift_days_moves_explicit_dates() -> None:
    request = TripRequest(date_from=date(2026, 11, 14))

    updated = patched(request, shift_days=2)

    assert updated.date_from == date(2026, 11, 16)
    assert updated.month == 11


def test_shift_days_uses_planned_dates_when_request_has_only_month() -> None:
    request = TripRequest(month=11)
    context = PatchContext(current_check_in=date(2026, 11, 10))

    updated = patched(request, context, shift_days=-3)

    assert updated.date_from == date(2026, 11, 7)


def test_shift_days_without_any_dates_asks_for_them() -> None:
    with pytest.raises(MissingInformation):
        patched(TripRequest(), shift_days=2)


def test_new_month_discards_old_exact_date() -> None:
    request = TripRequest(date_from=date(2026, 11, 14), month=11)

    updated = patched(request, month=12)

    assert updated.month == 12
    assert updated.date_from is None


def test_cheaper_by_percent_is_relative_to_current_plan_total() -> None:
    request = TripRequest(budget_total_rub=300_000)

    updated = patched(request, PatchContext(current_total_rub=200_000), cheaper_by_percent=10)

    assert updated.budget_total_rub == 180_000


def test_cheaper_without_any_price_reference_switches_to_economy() -> None:
    updated = patched(TripRequest(), cheaper_by_percent=15)

    assert updated.budget_total_rub is None
    assert updated.budget_style is BudgetStyle.ECONOMY


@pytest.mark.parametrize(
    "conflict",
    [
        {"shift_days": 2, "date_from": date(2026, 11, 20)},
        {"shift_days": 2, "month": 12},
        {"cheaper_by_percent": 10, "budget_total_rub": 100_000},
        {"clear": ["max_travel_hours"], "max_travel_hours": 6},
        {"clear": ["budget_total_rub"], "cheaper_by_percent": 10},
    ],
)
def test_contradicting_changes_are_rejected(conflict: dict) -> None:
    with pytest.raises(ValidationError):
        RequestPatch(**conflict)


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        RequestPatch(hotel_name="Рога и копыта")  # type: ignore[call-arg]


class TestResolveWindow:
    def test_exact_date_and_nights(self) -> None:
        window = resolve_window(TripRequest(date_from=date(2026, 11, 14), nights=5), TODAY)

        assert (window.check_in, window.check_out, window.nights) == (
            date(2026, 11, 14),
            date(2026, 11, 19),
            5,
        )

    def test_month_only_means_start_of_next_such_month_with_default_nights(self) -> None:
        window = resolve_window(TripRequest(month=11), TODAY)

        assert window.check_in == date(2026, 11, 10)
        assert window.nights == 7

    def test_past_month_rolls_over_to_next_year(self) -> None:
        window = resolve_window(TripRequest(month=3), TODAY)

        assert window.check_in == date(2027, 3, 10)

    def test_current_month_starts_after_minimum_lead_time(self) -> None:
        window = resolve_window(TripRequest(month=10), TODAY)

        assert window.check_in == date(2026, 10, 31)

    def test_past_date_is_an_error(self) -> None:
        with pytest.raises(DomainError, match="уже прошла"):
            resolve_window(TripRequest(date_from=date(2026, 10, 1)), TODAY)

    def test_no_dates_is_missing_information(self) -> None:
        with pytest.raises(MissingInformation):
            resolve_window(TripRequest(), TODAY)
