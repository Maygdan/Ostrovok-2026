"""Отель и предложение по нему (тариф на конкретные даты)."""

from datetime import date, time
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, computed_field

from odin.domain.tags import Tag


class MealPlan(StrEnum):
    RO = "RO"
    BB = "BB"
    HB = "HB"
    FB = "FB"
    AI = "AI"


MEAL_LABELS: dict[MealPlan, str] = {
    MealPlan.RO: "без питания",
    MealPlan.BB: "завтраки",
    MealPlan.HB: "полупансион",
    MealPlan.FB: "полный пансион",
    MealPlan.AI: "всё включено",
}
MEAL_ORDER = (MealPlan.RO, MealPlan.BB, MealPlan.HB, MealPlan.FB, MealPlan.AI)


class Hotel(BaseModel):
    """Постоянные свойства отеля, не зависящие от дат."""

    model_config = ConfigDict(frozen=True)

    id: str
    destination_id: str
    name: str
    stars: int
    rating: float
    area: str
    tags: list[Tag]
    distance_to_beach_m: int | None = None
    distance_to_center_km: float
    distance_to_airport_km: float
    distance_to_station_km: float | None = None
    pets_allowed: bool = False
    reception_24h: bool = True
    check_in_from: time = time(14, 0)
    check_out_until: time = time(12, 0)


class Cancellation(BaseModel):
    model_config = ConfigDict(frozen=True)

    free_until: date | None = None  # последний день бесплатной отмены; None — невозвратный тариф

    @property
    def refundable(self) -> bool:
        return self.free_until is not None


class HotelOffer(BaseModel):
    """Тариф отеля на даты и состав группы. Цена — за всё проживание, во всех номерах."""

    model_config = ConfigDict(frozen=True)

    hotel: Hotel
    rate_id: str
    room: str
    meal_plan: MealPlan
    check_in: date
    check_out: date
    rooms: int
    capacity_per_room: int
    total_price_rub: int
    cancellation: Cancellation

    @computed_field
    @property
    def id(self) -> str:
        return f"{self.hotel.id}:{self.rate_id}"

    def as_of(self, today: date) -> Self:
        """Тариф на сегодня: бесплатная отмена, срок которой вышел, уже не действует."""
        until = self.cancellation.free_until
        if until is None or until >= today:
            return self
        return self.model_copy(update={"cancellation": Cancellation()})

    @computed_field
    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days

    @computed_field
    @property
    def title(self) -> str:
        return f"{self.hotel.name} {self.hotel.stars}★, {self.room}, {MEAL_LABELS[self.meal_plan]}"
