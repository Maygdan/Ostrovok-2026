from datetime import date

from odin.api.summary import summarize
from odin.domain.request import TripRequest
from tests.factories import MOSCOW


def chips(**fields) -> dict[str, str]:
    request = TripRequest(origin="moscow", **fields)
    return {chip.label: chip.value for chip in summarize(request, MOSCOW, None)}


def test_exact_dates_are_described_as_the_start_of_the_trip_not_as_a_flight() -> None:
    assert chips(date_from=date(2026, 11, 10), nights=7)["Когда"] == "с 10 ноября, 7 ночей"


def test_nonstop_and_cancellation_wishes_are_visible() -> None:
    assert chips(max_stops=0)["Пересадки"] == "без пересадок"
    assert chips(max_stops=1)["Пересадки"] == "не больше 1"
    assert chips(free_cancellation=True)["Отмена"] == "бесплатная отмена отеля"
    assert "Отмена" not in chips()
    assert "Пересадки" not in chips()


def test_temperature_thresholds_keep_their_sign() -> None:
    thresholds = chips(min_sea_temp_c=22, min_air_temp_c=-5)

    assert thresholds["Вода"] == "от +22°C"
    assert thresholds["Воздух"] == "от \N{MINUS SIGN}5°C"
    assert chips(min_air_temp_c=0)["Воздух"] == "от 0°C"
