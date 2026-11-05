from datetime import date

import pytest

from odin.domain import formatting as fmt
from odin.domain.party import Party


def test_rub_uses_non_breaking_spaces() -> None:
    assert fmt.rub(118400) == f"118{fmt.NBSP}400{fmt.NBSP}₽"
    assert fmt.rub(950) == f"950{fmt.NBSP}₽"


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (1, "ночь"),
        (2, "ночи"),
        (5, "ночей"),
        (11, "ночей"),
        (21, "ночь"),
        (24, "ночи"),
        (112, "ночей"),
    ],
)
def test_plural(n: int, expected: str) -> None:
    assert fmt.plural(n, "ночь", "ночи", "ночей") == expected


@pytest.mark.parametrize(
    ("minutes", "expected"), [(225, "3 ч 45 мин"), (120, "2 ч"), (45, "45 мин")]
)
def test_duration(minutes: int, expected: str) -> None:
    assert fmt.duration(minutes) == expected


@pytest.mark.parametrize(
    ("celsius", "expected"),
    [(22, "+22°C"), (0, "0°C"), (-5, "\N{MINUS SIGN}5°C")],
)
def test_temperature_has_a_sign_that_matches_the_value(celsius: int, expected: str) -> None:
    assert fmt.temperature(celsius) == expected


def test_hours_uses_decimal_comma_and_drops_zero_fraction() -> None:
    assert fmt.hours(4.4) == "4,4 ч"
    assert fmt.hours(5.0) == "5 ч"


def test_date_range_within_and_across_months() -> None:
    assert fmt.date_range(date(2026, 11, 14), date(2026, 11, 21)) == "14–21 ноября"
    assert fmt.date_range(date(2026, 11, 28), date(2026, 12, 5)) == "28 ноября – 5 декабря"


def test_party_label_describes_children_and_pets() -> None:
    party = Party(adults=2, children_ages=[5], pets=["dog"])

    assert party.label() == "2 взрослых + 1 ребёнок (5 лет), с собакой"


def test_party_infants_do_not_take_a_paid_seat() -> None:
    party = Party(adults=2, children_ages=[1, 6])

    assert party.size == 4
    assert party.paying_seats == 3
    assert party.fare_units == 2.75
    assert party.needs_child_seat
