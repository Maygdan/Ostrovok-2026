from odin.domain.destination import Destination, MonthWeather
from odin.domain.ranking import rank
from odin.domain.request import TripRequest
from odin.domain.scoring.destinations import (
    DestinationFacts,
    destination_criteria,
    screen_destinations,
)
from odin.domain.tags import Tag
from tests.factories import ANTALYA, make_request


def facts(
    name: str,
    *,
    day: int = 28,
    sea: int | None = 26,
    rain: int = 1,
    minutes: int = 240,
    price: int = 120_000,
    tags: list[Tag] | None = None,
    visa_required: bool = False,
) -> DestinationFacts:
    destination = Destination(
        **{
            **ANTALYA.model_dump(),
            "id": name,
            "name": name,
            "tags": tags if tags is not None else [Tag.BEACH, Tag.FAMILY],
            "visa_required": visa_required,
            "entry_note": "нужна ПРО-виза" if visa_required else "",
        }
    )
    weather = MonthWeather(month=11, day_c=day, night_c=day - 8, sea_c=sea, rain_days=rain)
    return DestinationFacts(destination, weather, minutes, price)


def warm_sea_request(**fields) -> TripRequest:
    return make_request(tags=[Tag.BEACH], min_sea_temp_c=22, min_air_temp_c=22, **fields)


class TestScreening:
    def test_cold_sea_and_missing_sea_are_dropped_for_a_beach_trip(self) -> None:
        warm = facts("warm", sea=26)
        chilly = facts("chilly", sea=21)  # прохладно, но терпимо
        cold = facts("cold", sea=15)
        landlocked = facts("landlocked", sea=None)

        screened = screen_destinations([warm, chilly, cold, landlocked], warm_sea_request())

        assert [f.destination.name for f in screened.kept] == ["warm", "chilly"]
        reasons = {f.option.destination.name: f.reason for f in screened.dropped}
        assert "купаться нельзя" in reasons["cold"]
        assert reasons["landlocked"] == "нет моря"

    def test_a_named_threshold_of_zero_is_a_threshold_not_a_missing_value(self) -> None:
        chilly_sea = facts("north", sea=5)
        request = make_request(tags=[Tag.BEACH], min_sea_temp_c=0)

        screened = screen_destinations([chilly_sea], request)

        assert screened.kept == [chilly_sea], "вода +5°C выше порога 0°C; порог по умолчанию — 20°C"

    def test_sea_does_not_matter_for_a_city_trip(self) -> None:
        city = facts("city", sea=None, tags=[Tag.CITY])

        assert screen_destinations([city], make_request()).kept == [city]

    def test_travel_time_limit_and_budget_are_hard(self) -> None:
        near = facts("near", minutes=200, price=90_000)
        far = facts("far", minutes=9 * 60, price=90_000)
        expensive = facts("expensive", minutes=200, price=300_000)
        request = make_request(max_travel_hours=5, budget_total_rub=150_000)

        screened = screen_destinations([near, far, expensive], request)

        assert screened.kept == [near]
        assert screened.reasons == {"дорога дольше 5 ч": 1, "дороже всего бюджета": 1}

    def test_ski_requires_ski_slopes(self) -> None:
        beach = facts("beach")
        slopes = facts("slopes", tags=[Tag.SKI, Tag.MOUNTAINS])

        screened = screen_destinations([beach, slopes], make_request(tags=[Tag.SKI]))

        assert screened.kept == [slopes]


class TestRanking:
    def ranked(self, options: list[DestinationFacts], request: TripRequest):
        return rank(options, destination_criteria(request, options))

    def test_warm_sea_and_cheaper_price_win_and_are_explained(self) -> None:
        good = facts("good", sea=27, day=29, price=110_000)
        meh = facts("meh", sea=22, day=21, price=160_000)

        ranked = self.ranked([meh, good], warm_sea_request())

        assert [r.option.destination.name for r in ranked] == ["good", "meh"]
        assert any("вода +27°C" in note for note in ranked[0].pros)
        assert any("самое доступное" in note for note in ranked[0].pros)
        assert any("прохладнее желаемых" in note for note in ranked[1].cons)
        assert any("дороже самого дешёвого" in note for note in ranked[1].cons)

    def test_with_children_family_destinations_are_preferred(self) -> None:
        request = warm_sea_request()
        request.party.children_ages.append(5)
        family = facts("family", tags=[Tag.BEACH, Tag.FAMILY])
        party = facts("party", tags=[Tag.BEACH, Tag.NIGHTLIFE])

        ranked = self.ranked([party, family], request)

        assert ranked[0].option.destination.name == "family"
        assert any("с детьми" in note for note in ranked[0].pros)
        assert any("не лучший выбор для отдыха с детьми" in note for note in ranked[1].cons)

    def test_frost_is_written_with_a_minus_not_a_plus(self) -> None:
        frosty = facts("frosty", day=-5, sea=None, tags=[Tag.SKI])
        request = make_request(tags=[Tag.SKI], min_air_temp_c=-10)

        ranked = rank([frosty], destination_criteria(request, [frosty]))

        assert "днём \N{MINUS SIGN}5°C" in ranked[0].explanation().pros[0]

    def test_extreme_heat_and_rain_are_penalised(self) -> None:
        mild = facts("mild", day=30, rain=1)
        stuffy = facts("stuffy", day=38, rain=14)

        ranked = self.ranked([stuffy, mild], make_request())

        assert ranked[0].option.destination.name == "mild"
        cons = " ".join(ranked[1].cons)
        assert "жара" in cons
        assert "дождливо" in cons

    def test_visa_is_a_minor_drawback_not_a_dealbreaker(self) -> None:
        visa = facts("visa", visa_required=True)
        free = facts("free")

        ranked = self.ranked([visa, free], make_request())

        assert [r.option.destination.name for r in ranked] == ["free", "visa"]
        assert any("виза" in note for note in ranked[1].cons)
