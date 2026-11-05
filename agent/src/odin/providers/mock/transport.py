"""Рейсы и поезда: детерминированный генератор по расстоянию между городами.

Расписание (время вылета, перевозчик, номер рейса) зависит только от пары городов, а цена — ещё
и от даты. Поэтому повторный поиск возвращает то же самое, а при сдвиге дат тот же рейс
узнаётся по номеру и дешевеет или дорожает, как в жизни. Дальние маршруты получают варианты
с пересадкой.
"""

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from odin.domain.party import Party
from odin.domain.places import Place
from odin.domain.transport import Segment, TransportKind, TransportOffer
from odin.providers.mock.files import read_json

EARTH_RADIUS_KM = 6371.0
CRUISE_KMH = 780
TAXI_MINUTES = 30  # руление, взлёт и посадка сверх времени в воздухе
CONNECTION_FROM_KM = 3000  # на таких расстояниях добавляются варианты с пересадкой
CONNECTION_DISCOUNT = 0.78
HUBS = ("moscow", "saint-petersburg", "kazan", "yekaterinburg", "novosibirsk")
MAX_DETOUR = 1.3  # пересадка в хабе не должна удлинять путь больше чем на 30%
DEPARTURE_SLOTS = ("06:10", "08:30", "11:15", "14:40", "18:05", "21:30", "23:55")
LAYOVER_MINUTES = (55, 95, 150, 240, 420)


@dataclass(frozen=True)
class Carrier:
    name: str
    code: str
    price_factor: float
    baggage_included: bool
    refundable: bool
    pets_allowed: bool


CARRIERS = (
    Carrier("Север Эйр", "SE", 1.00, baggage_included=True, refundable=False, pets_allowed=True),
    Carrier("Волга Джет", "VJ", 0.85, baggage_included=False, refundable=False, pets_allowed=False),
    Carrier("Ассоль", "AS", 1.20, baggage_included=True, refundable=True, pets_allowed=True),
    Carrier("Балтик Лайн", "BL", 1.05, baggage_included=True, refundable=False, pets_allowed=True),
)


class Stations(BaseModel):
    a: str
    b: str


class Train(BaseModel):
    name: str
    number: str
    duration_min: int
    price_rub: int
    departures: list[str]


class RailRoute(BaseModel):
    """Маршрут между городами a и b; ходит в обе стороны."""

    a: str
    b: str
    stations: Stations
    trains: list[Train]


class MockTransport:
    def __init__(self, places: Mapping[str, Place], rail: Sequence[RailRoute]) -> None:
        self._places = places
        self._rail = rail

    @classmethod
    def from_files(cls) -> Self:
        places = {item["id"]: Place.model_validate(item) for item in read_json("places.json")}
        rail = [RailRoute.model_validate(item) for item in read_json("trains.json")]
        return cls(places, rail)

    async def search(
        self, origin: Place, destination: Place, day: date, party: Party
    ) -> list[TransportOffer]:
        return self._flights(origin, destination, day, party) + self._trains(
            origin, destination, day, party
        )

    def _flights(
        self, origin: Place, destination: Place, day: date, party: Party
    ) -> list[TransportOffer]:
        schedule = random.Random(f"{origin.id}>{destination.id}")
        prices = random.Random(f"{origin.id}>{destination.id}@{day.isoformat()}")
        distance = haversine_km(origin, destination)
        international = origin.country != destination.country
        if origin.airport_code == destination.airport_code:
            return []  # Сочи и Красная Поляна делят аэропорт: между ними не летают
        taken: set[str] = set()
        offers = []
        slots = sorted(schedule.sample(DEPARTURE_SLOTS, k=schedule.randint(3, 5)))
        for slot in slots:
            carrier = schedule.choice(CARRIERS)
            departs = _local(day, slot, origin.tz)
            arrives = _after(departs, _flight_minutes(distance), destination.tz)
            segment = Segment(
                carrier=carrier.name,
                number=_flight_number(schedule, carrier, taken),
                origin=_airport_label(origin),
                destination=_airport_label(destination),
                departs_at=departs,
                arrives_at=arrives,
            )
            price = _fare(prices, distance, day, slot, carrier, party)
            offers.append(_flight_offer([segment], [carrier], price, international))
        if distance > CONNECTION_FROM_KM:
            offers += self._connections(schedule, prices, origin, destination, day, party, taken)
        return offers

    def _connections(
        self,
        schedule: random.Random,
        prices: random.Random,
        origin: Place,
        destination: Place,
        day: date,
        party: Party,
        taken: set[str],
    ) -> list[TransportOffer]:
        distance = haversine_km(origin, destination)
        hubs = [
            self._places[hub_id]
            for hub_id in HUBS
            if hub_id in self._places
            and hub_id not in (origin.id, destination.id)
            and haversine_km(origin, self._places[hub_id])
            + haversine_km(self._places[hub_id], destination)
            <= MAX_DETOUR * distance
        ]
        international = origin.country != destination.country
        offers = []
        for hub in schedule.sample(hubs, k=min(2, len(hubs))):
            carriers = schedule.sample(CARRIERS, k=2)
            slot = schedule.choice(DEPARTURE_SLOTS[:4])
            departs = _local(day, slot, origin.tz)
            arrives_at_hub = _after(departs, _flight_minutes(haversine_km(origin, hub)), hub.tz)
            departs_from_hub = _after(arrives_at_hub, schedule.choice(LAYOVER_MINUTES), hub.tz)
            arrives = _after(
                departs_from_hub, _flight_minutes(haversine_km(hub, destination)), destination.tz
            )
            legs = [
                Segment(
                    carrier=carriers[0].name,
                    number=_flight_number(schedule, carriers[0], taken),
                    origin=_airport_label(origin),
                    destination=_airport_label(hub),
                    departs_at=departs,
                    arrives_at=arrives_at_hub,
                ),
                Segment(
                    carrier=carriers[1].name,
                    number=_flight_number(schedule, carriers[1], taken),
                    origin=_airport_label(hub),
                    destination=_airport_label(destination),
                    departs_at=departs_from_hub,
                    arrives_at=arrives,
                ),
            ]
            price = _fare(prices, distance, day, slot, carriers[0], party, CONNECTION_DISCOUNT)
            offers.append(_flight_offer(legs, carriers, price, international))
        return offers

    def _trains(
        self, origin: Place, destination: Place, day: date, party: Party
    ) -> list[TransportOffer]:
        offers = []
        for route in self._rail:
            if (origin.id, destination.id) == (route.a, route.b):
                start, finish = route.stations.a, route.stations.b
            elif (origin.id, destination.id) == (route.b, route.a):
                start, finish = route.stations.b, route.stations.a
            else:
                continue
            for train in route.trains:
                for slot in train.departures:
                    rng = random.Random(f"{train.number}@{day.isoformat()}@{slot}")
                    departs = _local(day, slot, origin.tz)
                    segment = Segment(
                        carrier=train.name,
                        number=f"{train.number}-{slot.replace(':', '')}",
                        origin=start,
                        destination=finish,
                        departs_at=departs,
                        arrives_at=_after(departs, train.duration_min, destination.tz),
                    )
                    price = train.price_rub * rng.uniform(0.9, 1.15) * party.fare_units
                    offers.append(
                        TransportOffer(
                            kind=TransportKind.TRAIN,
                            segments=[segment],
                            total_price_rub=int(round(price, -2)),
                            international=False,
                            baggage_included=True,
                            refundable=True,
                            pets_allowed=True,
                        )
                    )
        return offers


def haversine_km(a: Place, b: Place) -> float:
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    d_lat, d_lon = lat2 - lat1, math.radians(b.lon - a.lon)
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def _flight_minutes(distance_km: float) -> int:
    return round(distance_km / CRUISE_KMH * 60 + TAXI_MINUTES)


def _local(day: date, hhmm: str, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.fromisoformat(hhmm), tzinfo=tz)


def _after(moment: datetime, minutes: int, tz: ZoneInfo) -> datetime:
    """Момент через `minutes` минут, выраженный в поясе `tz` (арифметика — в UTC)."""
    return (moment.astimezone(UTC) + timedelta(minutes=minutes)).astimezone(tz)


def _airport_label(place: Place) -> str:
    return f"{place.name} {place.airport_code}"


def _flight_number(rng: random.Random, carrier: Carrier, taken: set[str]) -> str:
    while (number := f"{carrier.code}{rng.randint(100, 999)}") in taken:
        continue
    taken.add(number)
    return number


def _fare(
    rng: random.Random,
    distance_km: float,
    day: date,
    slot: str,
    carrier: Carrier,
    party: Party,
    discount: float = 1.0,
) -> int:
    """Цена для всей группы: базовая по расстоянию, с поправками на день, время и перевозчика."""
    hour = int(slot[:2])
    weekend = 1.1 if day.weekday() in (4, 6) else 1.0
    time_of_day = 0.85 if hour < 6 or hour >= 22 else 1.1 if 7 <= hour <= 10 else 1.0
    unit = (2800 + distance_km * 3.9) * weekend * time_of_day * rng.uniform(0.9, 1.25)
    return int(round(unit * carrier.price_factor * discount * party.fare_units, -2))


def _flight_offer(
    segments: list[Segment], carriers: Sequence[Carrier], price: int, international: bool
) -> TransportOffer:
    return TransportOffer(
        kind=TransportKind.FLIGHT,
        segments=segments,
        total_price_rub=price,
        international=international,
        baggage_included=all(c.baggage_included for c in carriers),
        refundable=all(c.refundable for c in carriers),
        pets_allowed=all(c.pets_allowed for c in carriers),
    )
