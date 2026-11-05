from datetime import date, timedelta

import pytest

from odin.domain.destination import Destination
from odin.domain.party import Party
from odin.domain.places import Place
from odin.domain.transfer import HubKind, TransferDirection, TransferKind
from odin.domain.transport import TransportKind
from odin.providers.interfaces import Providers
from odin.providers.mock.transport import LAYOVER_MINUTES
from tests.factories import CHECK_IN, CHECK_OUT, at

NOVEMBER_DAY = date(2026, 11, 10)
FAMILY = Party(adults=2, children_ages=[7])


async def place(providers: Providers, place_id: str) -> Place:
    found = await providers.catalog.get_place(place_id)
    assert found is not None
    return found


async def destination(providers: Providers, destination_id: str) -> Destination:
    found = await providers.catalog.get_destination(destination_id)
    assert found is not None
    return found


class TestCatalog:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Давай Анапу", "anapa"),
            ("хочу в Сочи на неделю", "sochi"),
            ("поехали на Байкал зимой", "baikal"),
            ("в Калининград на выходные", "kaliningrad"),
            ("хочу в Кисловодск лечиться", "kislovodsk"),
            ("по Карелии на машине", "karelia"),
            ("горный Алтай", "altai"),
            ("в Красную Поляну на лыжах", "krasnaya-polyana"),
            ("сочи", "sochi"),
            ("в Питер на выходные", "saint-petersburg"),
        ],
    )
    async def test_destination_is_found_in_free_text(
        self, providers: Providers, text: str, expected: str
    ) -> None:
        found = await providers.catalog.find_destination(text)

        assert found is not None
        assert found.id == expected

    async def test_unknown_text_finds_nothing(self, providers: Providers) -> None:
        assert await providers.catalog.find_destination("на Марс") is None

    async def test_departure_city_is_not_a_destination(self, providers: Providers) -> None:
        assert await providers.catalog.get_destination("moscow") is None
        assert await providers.catalog.find_destination("из Москвы") is None
        assert (await place(providers, "moscow")).airport_code == "SVO"

    async def test_any_known_city_can_be_a_departure_point(self, providers: Providers) -> None:
        found = await providers.catalog.find_place("вылетаем из Екатеринбурга")

        assert found is not None
        assert found.id == "yekaterinburg"

    async def test_every_destination_has_description_and_tags(self, providers: Providers) -> None:
        destinations = await providers.catalog.list_destinations()

        assert len(destinations) >= 8
        assert all(d.description and d.tags for d in destinations)


class TestWeather:
    async def test_anapa_in_september_is_warm_with_warm_water(self, providers: Providers) -> None:
        weather = await providers.weather.month_weather(await destination(providers, "anapa"), 9)

        assert weather is not None
        assert (weather.day_c, weather.sea_c) == (25, 22)

    async def test_cities_without_sea_have_no_water_temperature(self, providers: Providers) -> None:
        weather = await providers.weather.month_weather(await destination(providers, "kazan"), 11)

        assert weather is not None
        assert weather.sea_c is None

    async def test_every_destination_has_weather_for_every_month(
        self, providers: Providers
    ) -> None:
        for dest in await providers.catalog.list_destinations():
            for month in range(1, 13):
                assert await providers.weather.month_weather(dest, month) is not None, dest.id


class TestHotels:
    async def search(self, providers: Providers, dest: str, start: date, nights: int, party: Party):
        return await providers.hotels.search(
            await destination(providers, dest), start, start + timedelta(days=nights), party
        )

    async def test_every_destination_has_several_hotels_with_distinct_tradeoffs(
        self, providers: Providers
    ) -> None:
        for dest in await providers.catalog.list_destinations():
            offers = await self.search(providers, dest.id, NOVEMBER_DAY, 7, FAMILY)

            hotels = {offer.hotel.id for offer in offers}
            assert len(hotels) >= 3, dest.id
            assert len({offer.total_price_rub for offer in offers}) > 3, dest.id

    async def test_offers_carry_dates_meal_and_cancellation_terms(
        self, providers: Providers
    ) -> None:
        offers = await self.search(providers, "anapa", NOVEMBER_DAY, 7, FAMILY)

        flexible = next(o for o in offers if o.id == "aaq-dzhemete-family:ai-flex")
        saver = next(o for o in offers if o.id == "aaq-dzhemete-family:ai-saver")
        assert flexible.cancellation.free_until == NOVEMBER_DAY - timedelta(days=7)
        assert not saver.cancellation.refundable
        assert flexible.nights == 7
        assert flexible.total_price_rub > saver.total_price_rub

    async def test_high_season_costs_more_than_low_season(self, providers: Providers) -> None:
        november = await self.search(providers, "anapa", NOVEMBER_DAY, 7, FAMILY)
        july = await self.search(providers, "anapa", date(2027, 7, 10), 7, FAMILY)

        def price(offers) -> int:
            return next(o for o in offers if o.id == "aaq-dzhemete-family:ai-flex").total_price_rub

        assert price(july) > 1.5 * price(november)

    async def test_bigger_party_needs_more_rooms(self, providers: Providers) -> None:
        small = await self.search(providers, "anapa", NOVEMBER_DAY, 7, Party(adults=2))
        big = await self.search(
            providers, "anapa", NOVEMBER_DAY, 7, Party(adults=3, children_ages=[5, 9])
        )

        standard_small = next(o for o in small if o.id == "aaq-center-sea:bb-flex")
        standard_big = next(o for o in big if o.id == "aaq-center-sea:bb-flex")
        assert (standard_small.rooms, standard_big.rooms) == (1, 2)
        assert standard_big.total_price_rub == pytest.approx(
            2 * standard_small.total_price_rub, abs=200
        )

    async def test_hotel_sold_out_for_new_year_is_not_offered_then(
        self, providers: Providers
    ) -> None:
        new_year = await self.search(providers, "anapa", date(2026, 12, 29), 5, FAMILY)
        november = await self.search(providers, "anapa", NOVEMBER_DAY, 5, FAMILY)

        assert "aaq-dzhemete-family" not in {o.hotel.id for o in new_year}
        assert "aaq-dzhemete-family" in {o.hotel.id for o in november}

    async def test_new_year_nights_are_pricier(self, providers: Providers) -> None:
        december = await self.search(providers, "anapa", date(2026, 12, 15), 4, FAMILY)
        new_year = await self.search(providers, "anapa", date(2026, 12, 28), 4, FAMILY)

        def price(offers) -> int:
            return next(o for o in offers if o.id == "aaq-center-sea:bb-flex").total_price_rub

        assert price(new_year) > 1.2 * price(december)


class TestTransport:
    async def search(
        self, providers: Providers, origin: str, dest: str, day: date, party: Party = FAMILY
    ):
        return await providers.transport.search(
            await place(providers, origin), await place(providers, dest), day, party
        )

    async def test_search_is_deterministic(self, providers: Providers) -> None:
        first = await self.search(providers, "moscow", "anapa", NOVEMBER_DAY)
        second = await self.search(providers, "moscow", "anapa", NOVEMBER_DAY)

        assert first == second

    async def test_same_flights_run_on_other_dates_at_other_prices(
        self, providers: Providers
    ) -> None:
        first = await self.search(providers, "moscow", "anapa", NOVEMBER_DAY)
        later = await self.search(providers, "moscow", "anapa", NOVEMBER_DAY + timedelta(days=2))

        assert [o.id for o in first] == [o.id for o in later], "расписание не зависит от даты"
        assert [o.departs_at.time() for o in first] == [o.departs_at.time() for o in later]
        assert [o.departs_at.date() for o in later] == [NOVEMBER_DAY + timedelta(days=2)] * len(
            later
        )
        assert [o.total_price_rub for o in first] != [o.total_price_rub for o in later]

    async def test_times_are_local_to_each_airport(self, providers: Providers) -> None:
        offers = await self.search(providers, "moscow", "baikal", NOVEMBER_DAY)
        direct = next(o for o in offers if o.stops == 0)

        assert direct.departs_at.utcoffset() == timedelta(hours=3)
        assert direct.arrives_at.utcoffset() == timedelta(hours=8)
        assert direct.departs_at.date() == NOVEMBER_DAY
        wall_clock_gap = direct.arrives_at.replace(tzinfo=None) - direct.departs_at.replace(
            tzinfo=None
        )
        assert wall_clock_gap == timedelta(minutes=direct.duration_minutes) + timedelta(hours=5)

    async def test_long_routes_offer_connections_with_realistic_layovers(
        self, providers: Providers
    ) -> None:
        offers = await self.search(providers, "moscow", "baikal", NOVEMBER_DAY)

        connections = [o for o in offers if o.stops == 1]
        assert connections
        for offer in connections:
            assert offer.layovers_minutes[0] in LAYOVER_MINUTES
            assert offer.segments[0].destination != offer.segments[1].destination
            assert offer.segments[0].arrives_at <= offer.segments[1].departs_at
        assert min(o.total_price_rub for o in connections) < min(
            o.total_price_rub for o in offers if o.stops == 0
        )

    async def test_short_routes_have_only_direct_flights(self, providers: Providers) -> None:
        offers = await self.search(providers, "moscow", "anapa", NOVEMBER_DAY)

        assert offers
        assert {o.stops for o in offers} == {0}

    async def test_trains_run_in_both_directions_only_where_rails_exist(
        self, providers: Providers
    ) -> None:
        there = await self.search(providers, "moscow", "saint-petersburg", NOVEMBER_DAY)
        back = await self.search(providers, "saint-petersburg", "moscow", NOVEMBER_DAY)
        sea = await self.search(providers, "moscow", "anapa", NOVEMBER_DAY)

        trains_there = [o for o in there if o.kind is TransportKind.TRAIN]
        trains_back = [o for o in back if o.kind is TransportKind.TRAIN]
        assert trains_there
        assert trains_back
        assert "Ленинградский" in trains_there[0].segments[0].origin
        assert "Ленинградский" in trains_back[0].segments[0].destination
        assert not [o for o in sea if o.kind is TransportKind.TRAIN]

    async def test_places_sharing_an_airport_have_no_flights_between_them(
        self, providers: Providers
    ) -> None:
        offers = await self.search(providers, "sochi", "krasnaya-polyana", NOVEMBER_DAY)

        assert offers, "а местная электричка между ними есть"
        assert {o.kind for o in offers} == {TransportKind.TRAIN}

    async def test_ids_are_unique_within_a_search(self, providers: Providers) -> None:
        for origin, dest in [
            ("moscow", "saint-petersburg"),
            ("moscow", "baikal"),
            ("kazan", "anapa"),
        ]:
            offers = await self.search(providers, origin, dest, NOVEMBER_DAY)

            ids = [o.id for o in offers]
            assert len(ids) == len(set(ids)), (origin, dest)

    async def test_price_follows_party_composition(self, providers: Providers) -> None:
        adults = await self.search(providers, "moscow", "anapa", NOVEMBER_DAY, Party(adults=2))
        family = await self.search(providers, "moscow", "anapa", NOVEMBER_DAY, FAMILY)

        for single, group in zip(adults, family, strict=True):
            assert group.total_price_rub == pytest.approx(
                single.total_price_rub * 2.75 / 2, abs=200
            )

    async def test_every_trip_is_domestic(self, providers: Providers) -> None:
        for destination_id in ("anapa", "kaliningrad", "baikal"):
            offers = await self.search(providers, "moscow", destination_id, NOVEMBER_DAY)

            assert offers
            assert not any(o.international for o in offers), destination_id

    async def test_every_destination_is_reachable_from_moscow(self, providers: Providers) -> None:
        for dest in await providers.catalog.list_destinations():
            offers = await self.search(providers, "moscow", dest.id, NOVEMBER_DAY)

            assert offers, dest.id


class TestTransfers:
    async def search(self, providers: Providers, hub: HubKind, direction: TransferDirection, when):
        hotels = await providers.hotels.search(
            await destination(providers, "saint-petersburg"),
            NOVEMBER_DAY,
            NOVEMBER_DAY + timedelta(days=2),
            FAMILY,
        )
        hotel = next(o.hotel for o in hotels if o.hotel.id == "led-nevsky-grand")
        return await providers.transfers.search(hotel, hub, direction, when, FAMILY)

    async def test_arrival_transfers_wait_until_the_group_is_ready(
        self, providers: Providers
    ) -> None:
        ready = at(CHECK_IN, "13:10")

        offers = {
            o.kind: o
            for o in await self.search(providers, HubKind.STATION, TransferDirection.IN, ready)
        }

        assert offers[TransferKind.TAXI].pickup_at == ready
        assert offers[TransferKind.SHUTTLE].pickup_at >= ready
        assert offers[TransferKind.SHUTTLE].pickup_at.minute in (0, 30)
        assert all(o.pickup_at >= ready for o in offers.values())

    async def test_departure_transfers_get_to_the_hub_before_the_deadline(
        self, providers: Providers
    ) -> None:
        deadline = at(CHECK_OUT, "12:40")

        offers = await self.search(providers, HubKind.STATION, TransferDirection.OUT, deadline)

        assert offers
        assert all(o.arrive_at <= deadline for o in offers)

    async def test_kinds_differ_in_price_comfort_and_pet_policy(self, providers: Providers) -> None:
        offers = {
            o.kind: o
            for o in await self.search(
                providers, HubKind.STATION, TransferDirection.IN, at(CHECK_IN, "13:00")
            )
        }

        assert (
            offers[TransferKind.PRIVATE].total_price_rub > offers[TransferKind.TAXI].total_price_rub
        )
        assert (
            offers[TransferKind.TAXI].total_price_rub > offers[TransferKind.SHUTTLE].total_price_rub
        )
        assert (
            offers[TransferKind.SHUTTLE].duration_minutes
            > offers[TransferKind.TAXI].duration_minutes
        )
        assert offers[TransferKind.TAXI].child_seat
        assert not offers[TransferKind.SHUTTLE].child_seat
        assert not offers[TransferKind.SHUTTLE].pets_allowed
        assert offers[TransferKind.PRIVATE].meet_and_greet

    async def test_night_rides_cost_more(self, providers: Providers) -> None:
        day = {
            o.kind: o
            for o in await self.search(
                providers, HubKind.STATION, TransferDirection.IN, at(CHECK_IN, "14:00")
            )
        }
        night = {
            o.kind: o
            for o in await self.search(
                providers, HubKind.STATION, TransferDirection.IN, at(CHECK_IN, "02:00")
            )
        }

        assert night[TransferKind.TAXI].total_price_rub > day[TransferKind.TAXI].total_price_rub

    async def test_far_hotels_have_no_public_transport_option(self, providers: Providers) -> None:
        hotels = await providers.hotels.search(
            await destination(providers, "krasnaya-polyana"),
            NOVEMBER_DAY,
            NOVEMBER_DAY + timedelta(days=3),
            FAMILY,
        )
        far_hotel = next(o.hotel for o in hotels if o.hotel.id == "kp-gorki-grand")

        offers = await providers.transfers.search(
            far_hotel, HubKind.AIRPORT, TransferDirection.IN, at(CHECK_IN, "13:00"), FAMILY
        )

        assert TransferKind.PUBLIC not in {o.kind for o in offers}


class TestCheckout:
    async def test_payment_is_confirmed_with_a_transaction_id(self, providers: Providers) -> None:
        receipt = await providers.payments.charge(150_000, "Поездка", "card", "cart-1")

        assert receipt.amount_rub == 150_000
        assert receipt.transaction_id.startswith("pay_")
        assert receipt.paid_at.tzinfo is not None

    async def test_repeating_a_charge_with_the_same_key_does_not_charge_twice(
        self, providers: Providers
    ) -> None:
        first = await providers.payments.charge(150_000, "Поездка", "card", "cart-1")
        again = await providers.payments.charge(150_000, "Поездка", "card", "cart-1")
        other = await providers.payments.charge(150_000, "Поездка", "card", "cart-2")

        assert again == first
        assert other.transaction_id != first.transaction_id
