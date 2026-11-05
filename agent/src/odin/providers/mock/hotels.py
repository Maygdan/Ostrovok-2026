"""Отели: тарифы, сезонные цены, занятые даты. Данные — в hotels.json."""

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from odin.domain.destination import Destination
from odin.domain.hotel import Cancellation, Hotel, HotelOffer, MealPlan
from odin.domain.party import Party
from odin.providers.mock.files import read_json

NEW_YEAR_FACTOR = 1.35  # надбавка к цене с 28 декабря по 8 января


class RateRecord(BaseModel):
    id: str
    room: str
    meal: MealPlan
    price_per_night: int = Field(description="За номер в сутки при сезонном индексе 1.0")
    free_cancel_days: int | None = Field(description="За сколько дней до заезда отмена бесплатна")
    capacity: int


class SoldOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    start: date = Field(alias="from")
    end: date = Field(alias="to")


class HotelRecord(Hotel):
    rates: list[RateRecord]
    sold_out: list[SoldOut] = Field(default_factory=list)

    def to_hotel(self) -> Hotel:
        return Hotel.model_validate(self.model_dump(exclude={"rates", "sold_out"}))

    def is_available(self, check_in: date, check_out: date) -> bool:
        return not any(
            period.start < check_out and check_in <= period.end for period in self.sold_out
        )


class MockHotels:
    def __init__(
        self, records: Sequence[HotelRecord], price_index: Mapping[str, Sequence[float]]
    ) -> None:
        self._by_destination: dict[str, list[HotelRecord]] = defaultdict(list)
        for record in records:
            self._by_destination[record.destination_id].append(record)
        self._price_index = price_index

    @classmethod
    def from_files(cls) -> Self:
        data = read_json("hotels.json")
        records = [HotelRecord.model_validate(item) for item in data["hotels"]]
        return cls(records, data["price_index"])

    async def search(
        self, destination: Destination, check_in: date, check_out: date, party: Party
    ) -> list[HotelOffer]:
        offers = []
        for record in self._by_destination.get(destination.id, ()):
            if not record.is_available(check_in, check_out):
                continue
            hotel = record.to_hotel()
            for rate in record.rates:
                rooms = math.ceil(party.size / rate.capacity)
                nightly = self._stay_price(destination.id, rate, check_in, check_out)
                free_until = None
                if rate.free_cancel_days is not None:
                    free_until = check_in - timedelta(days=rate.free_cancel_days)
                offers.append(
                    HotelOffer(
                        hotel=hotel,
                        rate_id=rate.id,
                        room=rate.room,
                        meal_plan=rate.meal,
                        check_in=check_in,
                        check_out=check_out,
                        rooms=rooms,
                        capacity_per_room=rate.capacity,
                        total_price_rub=int(round(rooms * nightly, -2)),
                        cancellation=Cancellation(free_until=free_until),
                    )
                )
        return offers

    def _stay_price(
        self, destination_id: str, rate: RateRecord, check_in: date, check_out: date
    ) -> float:
        """Цена одного номера за все ночи: у каждой ночи свой сезонный коэффициент."""
        index = self._price_index[destination_id]
        nights = (check_out - check_in).days
        days = (check_in + timedelta(days=n) for n in range(nights))
        return sum(
            rate.price_per_night * index[day.month - 1] * _holiday_factor(day) for day in days
        )


def _holiday_factor(day: date) -> float:
    in_new_year = (day.month == 12 and day.day >= 28) or (day.month == 1 and day.day <= 8)
    return NEW_YEAR_FACTOR if in_new_year else 1.0
