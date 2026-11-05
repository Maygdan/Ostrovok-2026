"""Трансфер между аэропортом или вокзалом и отелем."""

from datetime import timedelta
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, computed_field


class TransferKind(StrEnum):
    TAXI = "taxi"
    SHUTTLE = "shuttle"
    PRIVATE = "private"
    PUBLIC = "public"


TRANSFER_LABELS: dict[TransferKind, str] = {
    TransferKind.TAXI: "такси",
    TransferKind.SHUTTLE: "групповой трансфер",
    TransferKind.PRIVATE: "индивидуальный трансфер с встречей",
    TransferKind.PUBLIC: "общественный транспорт",
}


class TransferDirection(StrEnum):
    IN = "in"  # из аэропорта или вокзала в отель
    OUT = "out"  # из отеля в аэропорт или на вокзал


class HubKind(StrEnum):
    AIRPORT = "airport"
    STATION = "station"


class TransferOffer(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: TransferKind
    direction: TransferDirection
    hub: HubKind
    pickup_at: AwareDatetime  # у терминала (IN) или у отеля (OUT)
    duration_minutes: int
    total_price_rub: int
    child_seat: bool
    pets_allowed: bool
    meet_and_greet: bool

    @computed_field
    @property
    def id(self) -> str:
        return self.kind.value

    @computed_field
    @property
    def arrive_at(self) -> AwareDatetime:
        return self.pickup_at + timedelta(minutes=self.duration_minutes)

    @computed_field
    @property
    def title(self) -> str:
        hub = "аэропорта" if self.hub is HubKind.AIRPORT else "вокзала"
        if self.direction is TransferDirection.IN:
            route = f"от {hub} до отеля"
        else:
            route = f"от отеля до {hub}"
        return f"{TRANSFER_LABELS[self.kind].capitalize()} {route}"
