"""Перелёты и поезда: сегменты пути и предложение целиком (в одну сторону)."""

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, computed_field

from odin.domain.formatting import plural
from odin.domain.timeutil import to_minutes


class TransportKind(StrEnum):
    FLIGHT = "flight"
    TRAIN = "train"


class Segment(BaseModel):
    """Один рейс или поезд. Время локальное для пункта (aware-datetime с его поясом)."""

    model_config = ConfigDict(frozen=True)

    carrier: str
    number: str
    origin: str
    destination: str
    departs_at: AwareDatetime
    arrives_at: AwareDatetime


class TransportOffer(BaseModel):
    """Путь в одну сторону, возможно с пересадками. Цена — за всю группу."""

    model_config = ConfigDict(frozen=True)

    kind: TransportKind
    segments: list[Segment] = Field(min_length=1)
    total_price_rub: int
    international: bool
    baggage_included: bool
    refundable: bool
    pets_allowed: bool

    @computed_field
    @property
    def id(self) -> str:
        return "+".join(segment.number for segment in self.segments)

    @computed_field
    @property
    def departs_at(self) -> datetime:
        return self.segments[0].departs_at

    @computed_field
    @property
    def arrives_at(self) -> datetime:
        return self.segments[-1].arrives_at

    @computed_field
    @property
    def duration_minutes(self) -> int:
        return to_minutes(self.arrives_at - self.departs_at)

    @computed_field
    @property
    def stops(self) -> int:
        return len(self.segments) - 1

    @computed_field
    @property
    def title(self) -> str:
        first, last = self.segments[0], self.segments[-1]
        numbers = " + ".join(f"{s.carrier} {s.number}" for s in self.segments)
        stops = plural(self.stops, "пересадка", "пересадки", "пересадок")
        suffix = f" ({self.stops} {stops})" if self.stops else ""
        return f"{numbers}: {first.origin} → {last.destination}{suffix}"

    @property
    def layovers_minutes(self) -> list[int]:
        """Длительность каждой пересадки в минутах."""
        pairs = zip(self.segments, self.segments[1:], strict=False)
        return [to_minutes(nxt.departs_at - prev.arrives_at) for prev, nxt in pairs]

    @property
    def arrival_buffer(self) -> timedelta:
        """Сколько нужно после прибытия, чтобы выйти из терминала или с вокзала."""
        if self.kind is TransportKind.TRAIN:
            return timedelta(minutes=15)
        return timedelta(minutes=60 if self.international else 40)

    @property
    def departure_buffer(self) -> timedelta:
        """За сколько до отправления нужно быть на месте."""
        if self.kind is TransportKind.TRAIN:
            return timedelta(minutes=30)
        return timedelta(minutes=180 if self.international else 120)

    @property
    def door_to_door_minutes(self) -> int:
        """Время в пути вместе с обязательными запасами на аэропорт или вокзал."""
        buffers = self.arrival_buffer + self.departure_buffer
        return self.duration_minutes + to_minutes(buffers)
