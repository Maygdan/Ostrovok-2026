"""План поездки: выбранные предложения по частям, объяснения, проблемы стыковок."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field

from odin.domain.destination import Destination, MonthWeather
from odin.domain.hotel import HotelOffer
from odin.domain.party import Party
from odin.domain.request import TripRequest
from odin.domain.transfer import TransferOffer
from odin.domain.transport import TransportOffer

type Offer = HotelOffer | TransportOffer | TransferOffer


class Slot(StrEnum):
    """Часть плана. Значение совпадает с именем поля в TripPlan."""

    OUTBOUND = "outbound"
    HOTEL = "hotel"
    INBOUND = "inbound"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"


SLOT_LABELS: dict[Slot, str] = {
    Slot.OUTBOUND: "Дорога туда",
    Slot.HOTEL: "Отель",
    Slot.INBOUND: "Дорога обратно",
    Slot.TRANSFER_IN: "Трансфер в отель",
    Slot.TRANSFER_OUT: "Трансфер из отеля",
}
MAIN_SLOTS = (Slot.OUTBOUND, Slot.HOTEL, Slot.INBOUND)
TRANSFER_SLOTS = (Slot.TRANSFER_IN, Slot.TRANSFER_OUT)


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class IssueCode(StrEnum):
    ARRIVES_BEFORE_CHECK_IN = "arrives_before_check_in"
    ARRIVES_AFTER_CHECK_IN = "arrives_after_check_in"
    LATE_ARRIVAL = "late_arrival"
    WAIT_FOR_CHECK_IN = "wait_for_check_in"
    NIGHT_ARRIVAL_AT_HOTEL = "night_arrival_at_hotel"
    TRANSFER_BEFORE_LANDING = "transfer_before_landing"
    DEPARTS_BEFORE_CHECK_OUT = "departs_before_check_out"
    DEPARTS_AFTER_CHECK_OUT = "departs_after_check_out"
    NIGHT_PICKUP = "night_pickup"
    LONG_GAP_AFTER_CHECK_OUT = "long_gap_after_check_out"
    MISSED_DEPARTURE = "missed_departure"
    SHORT_LAYOVER = "short_layover"
    LONG_LAYOVER = "long_layover"
    STAY_MISMATCH = "stay_mismatch"
    PETS_NOT_ALLOWED = "pets_not_allowed"
    NOT_ENOUGH_ROOM = "not_enough_room"
    OVER_BUDGET = "over_budget"
    VISA = "visa"


class Issue(BaseModel):
    """Проблема или предупреждение о плане. ERROR блокирует оформление корзины."""

    model_config = ConfigDict(frozen=True)

    severity: Severity
    code: IssueCode
    message: str
    slots: list[Slot] = Field(default_factory=list)


class Explanation(BaseModel):
    """Почему выбрано это предложение, чем пришлось пожертвовать и какие есть риски."""

    model_config = ConfigDict(frozen=True)

    score: float
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class TripPlan(BaseModel):
    """Собранная поездка. Неизменяема: пересборка возвращает новый план с новой ревизией."""

    model_config = ConfigDict(frozen=True)

    revision: int = 1
    destination: Destination
    weather: MonthWeather | None = None
    check_in: date
    check_out: date
    outbound: TransportOffer | None = None
    hotel: HotelOffer | None = None
    inbound: TransportOffer | None = None
    transfer_in: TransferOffer | None = None
    transfer_out: TransferOffer | None = None
    explanations: dict[Slot, Explanation] = Field(default_factory=dict)
    pinned: list[Slot] = Field(
        default_factory=list, description="Части, которые пользователь выбрал сам"
    )
    issues: list[Issue] = Field(default_factory=list)
    built_for: TripRequest = Field(description="Снимок запроса, под который собран план")

    @property
    def party(self) -> Party:
        return self.built_for.party

    @computed_field
    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days

    @computed_field
    @property
    def total_price_rub(self) -> int:
        offers = (self.get(slot) for slot in Slot)
        return sum(offer.total_price_rub for offer in offers if offer is not None)

    @property
    def missing_slots(self) -> list[Slot]:
        return [slot for slot in Slot if self.get(slot) is None]

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity is Severity.ERROR]

    def get(self, slot: Slot) -> Offer | None:
        return getattr(self, slot.value)


class ChangeKind(StrEnum):
    KEPT = "kept"
    UPDATED = "updated"
    REPLACED = "replaced"
    ADDED = "added"
    REMOVED = "removed"


class SlotChange(BaseModel):
    """Что произошло с частью плана при пересборке."""

    slot: Slot
    kind: ChangeKind
    before: str | None = None
    after: str | None = None
    price_delta_rub: int = 0


class PlanDiff(BaseModel):
    changes: list[SlotChange]
    price_delta_rub: int
