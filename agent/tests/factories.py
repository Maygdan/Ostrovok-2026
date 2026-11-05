"""Фабрики доменных объектов для тестов.

make_plan() даёт «счастливый» план без единой проблемы стыковок; тесты меняют в нём
только то, что проверяют.
"""

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from odin.domain.destination import Destination, MonthWeather
from odin.domain.hotel import Cancellation, Hotel, HotelOffer, MealPlan
from odin.domain.places import Place
from odin.domain.plan import TripPlan
from odin.domain.request import TripRequest
from odin.domain.tags import Tag
from odin.domain.transfer import HubKind, TransferDirection, TransferKind, TransferOffer
from odin.domain.transport import Segment, TransportKind, TransportOffer

MSK = ZoneInfo("Europe/Moscow")
IST = ZoneInfo("Europe/Istanbul")

CHECK_IN = date(2026, 11, 14)
CHECK_OUT = date(2026, 11, 21)

MOSCOW = Place(
    id="moscow",
    name="Москва",
    country="Россия",
    timezone="Europe/Moscow",
    lat=55.75,
    lon=37.62,
    airport_code="SVO",
)
ANTALYA = Destination(
    id="antalya",
    name="Анталья",
    country="Турция",
    timezone="Europe/Istanbul",
    lat=36.9,
    lon=30.7,
    airport_code="AYT",
    description="Курорт на Средиземном море",
    tags=[Tag.BEACH, Tag.FAMILY],
)
ANTALYA_NOVEMBER = MonthWeather(month=11, day_c=21, night_c=11, sea_c=22, rain_days=8)


def at(day: date, hhmm: str, tz: ZoneInfo = IST) -> datetime:
    hour, minute = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)


def make_flight(
    departs: datetime,
    arrives: datetime,
    *,
    number: str = "SE413",
    price: int = 30_000,
    **overrides: Any,
) -> TransportOffer:
    segment = Segment(
        carrier="Север Эйр",
        number=number,
        origin="Москва SVO",
        destination="Анталья AYT",
        departs_at=departs,
        arrives_at=arrives,
    )
    fields: dict[str, Any] = {
        "kind": TransportKind.FLIGHT,
        "segments": [segment],
        "total_price_rub": price,
        "international": True,
        "baggage_included": True,
        "refundable": False,
        "pets_allowed": False,
    } | overrides
    return TransportOffer(**fields)


def make_connection(layover_minutes: int, *, price: int = 24_000) -> TransportOffer:
    """Перелёт с одной пересадкой в Стамбуле: 08:00 → ... → прибытие в Анталью."""
    first_arrives = at(CHECK_IN, "11:00", IST)
    second_departs = first_arrives + timedelta(minutes=layover_minutes)
    legs = [
        Segment(
            carrier="Север Эйр",
            number="SE100",
            origin="Москва SVO",
            destination="Стамбул IST",
            departs_at=at(CHECK_IN, "08:00", MSK),
            arrives_at=first_arrives,
        ),
        Segment(
            carrier="Босфор Эйр",
            number="BA200",
            origin="Стамбул IST",
            destination="Анталья AYT",
            departs_at=second_departs,
            arrives_at=second_departs + timedelta(hours=1, minutes=20),
        ),
    ]
    return TransportOffer(
        kind=TransportKind.FLIGHT,
        segments=legs,
        total_price_rub=price,
        international=True,
        baggage_included=True,
        refundable=False,
        pets_allowed=False,
    )


def make_hotel(**overrides: Any) -> Hotel:
    fields: dict[str, Any] = {
        "id": "ayt-test",
        "destination_id": "antalya",
        "name": "Test Resort",
        "stars": 5,
        "rating": 8.8,
        "area": "Лара",
        "tags": [Tag.POOL, Tag.KIDS_CLUB],
        "distance_to_beach_m": 100,
        "distance_to_center_km": 12.0,
        "distance_to_airport_km": 15.0,
        "pets_allowed": False,
    } | overrides
    return Hotel(**fields)


def make_hotel_offer(
    *,
    hotel: Hotel | None = None,
    price: int = 84_000,
    meal_plan: MealPlan = MealPlan.AI,
    free_until: date | None = date(2026, 11, 7),
    **overrides: Any,
) -> HotelOffer:
    fields: dict[str, Any] = {
        "hotel": hotel or make_hotel(),
        "rate_id": "ai-flex",
        "room": "Семейный номер",
        "meal_plan": meal_plan,
        "check_in": CHECK_IN,
        "check_out": CHECK_OUT,
        "rooms": 1,
        "capacity_per_room": 4,
        "total_price_rub": price,
        "cancellation": Cancellation(free_until=free_until),
    } | overrides
    return HotelOffer(**fields)


def make_transfer(
    direction: TransferDirection,
    pickup_at: datetime,
    *,
    kind: TransferKind = TransferKind.TAXI,
    duration_minutes: int = 45,
    price: int = 3_000,
    **overrides: Any,
) -> TransferOffer:
    fields: dict[str, Any] = {
        "kind": kind,
        "direction": direction,
        "hub": HubKind.AIRPORT,
        "pickup_at": pickup_at,
        "duration_minutes": duration_minutes,
        "total_price_rub": price,
        "child_seat": True,
        "pets_allowed": True,
        "meet_and_greet": False,
    } | overrides
    return TransferOffer(**fields)


def make_request(**overrides: Any) -> TripRequest:
    fields: dict[str, Any] = {
        "origin": "moscow",
        "destination": "antalya",
        "date_from": CHECK_IN,
        "nights": 7,
    } | overrides
    return TripRequest(**fields)


def make_plan(**overrides: Any) -> TripPlan:
    """Рейс 08:30 → 12:05, трансфер в 13:05 (приедем в 13:50, заселение с 14:00),
    обратно вылет в 15:40, выезд из отеля в 11:50 (в аэропорту к 12:35, нужно к 12:40)."""
    fields: dict[str, Any] = {
        "destination": ANTALYA,
        "weather": ANTALYA_NOVEMBER,
        "check_in": CHECK_IN,
        "check_out": CHECK_OUT,
        "outbound": make_flight(at(CHECK_IN, "08:30", MSK), at(CHECK_IN, "12:05")),
        "hotel": make_hotel_offer(),
        "inbound": make_flight(
            at(CHECK_OUT, "15:40"), at(CHECK_OUT, "21:00", MSK), number="SE414", price=28_000
        ),
        "transfer_in": make_transfer(TransferDirection.IN, at(CHECK_IN, "13:05")),
        "transfer_out": make_transfer(TransferDirection.OUT, at(CHECK_OUT, "11:50")),
        "built_for": make_request(),
    } | overrides
    return TripPlan(**fields)
