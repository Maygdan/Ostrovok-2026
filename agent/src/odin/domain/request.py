"""Запрос на поездку: структурированное понимание пожеланий и правила их изменения."""

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from odin.domain.errors import MissingInformation
from odin.domain.hotel import MealPlan
from odin.domain.party import ChildAge, Party, PetKind
from odin.domain.tags import Tag
from odin.domain.transport import TransportKind

# Начало допущения о городе вылета по умолчанию: оно перестаёт быть верным, как только
# пользователь назвал город сам, и apply_patch его убирает.
DEFAULT_ORIGIN_NOTE = "Вылет из города "


type Limit = Literal[
    "budget_total_rub",
    "max_travel_hours",
    "min_air_temp_c",
    "min_sea_temp_c",
    "min_stars",
    "meal_plan",
    "max_stops",
]
"""Ограничение запроса, которое можно снять: пользователь передумал или оно не важно."""


class BudgetStyle(StrEnum):
    ECONOMY = "economy"
    STANDARD = "standard"
    PREMIUM = "premium"


class TripRequest(BaseModel):
    """Всё, что известно о желаемой поездке. Неизвестное остаётся пустым, а не выдумывается."""

    origin: str | None = None
    destination: str | None = None
    month: int | None = Field(None, ge=1, le=12)
    date_from: date | None = None
    nights: int | None = Field(None, ge=1, le=60)
    party: Party = Field(default_factory=Party)
    budget_total_rub: int | None = Field(None, gt=0)
    budget_style: BudgetStyle = BudgetStyle.STANDARD
    max_travel_hours: float | None = Field(None, gt=0)
    min_air_temp_c: int | None = None
    min_sea_temp_c: int | None = None
    tags: list[Tag] = Field(default_factory=list)
    min_stars: int | None = Field(None, ge=1, le=5)
    meal_plan: MealPlan | None = None
    max_stops: int | None = Field(None, ge=0, le=2)
    free_cancellation: bool = False
    transport_kinds: list[TransportKind] = Field(
        default_factory=lambda: list(TransportKind), min_length=1
    )
    notes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @property
    def wants_sea(self) -> bool:
        return Tag.BEACH in self.tags or self.min_sea_temp_c is not None

    @property
    def missing(self) -> list[str]:
        """Без чего поиск невозможен: город вылета и хотя бы месяц поездки."""
        missing = []
        if self.origin is None:
            missing.append("origin")
        if self.month is None and self.date_from is None:
            missing.append("dates")
        return missing


class RequestPatch(BaseModel):
    """Изменение запроса. Все поля необязательны: задаётся только то, что изменилось.

    Города (origin, destination) здесь — id из каталога; свободный текст в id превращает
    слой инструментов, потому что для этого нужен каталог.
    """

    model_config = ConfigDict(extra="forbid")

    origin: str | None = Field(None, description="Город вылета: название («Москва») или id.")
    destination: str | None = Field(
        None,
        description="Выбранное направление: название («Казань») или id. "
        "Задавайте, только когда пользователь выбрал направление.",
    )
    month: int | None = Field(
        None, ge=1, le=12, description="Месяц поездки (1–12), если точные даты неизвестны."
    )
    date_from: date | None = Field(
        None,
        description="Дата начала поездки — день заезда в отель, YYYY-MM-DD. Ночной поезд и "
        "дальний перелёт при этом отправятся накануне. Если задана, месяц не нужен.",
    )
    shift_days: int | None = Field(
        None,
        ge=-60,
        le=60,
        description="Сдвинуть текущие даты на N дней: плюс — позже, минус — раньше. "
        "Для просьб вроде «на два дня позже»; нельзя вместе с date_from и month.",
    )
    nights: int | None = Field(None, ge=1, le=60, description="Сколько ночей в отеле.")
    adults: int | None = Field(None, ge=1, le=9, description="Число взрослых.")
    children_ages: list[ChildAge] | None = Field(
        None, description="Возраст каждого ребёнка. Полностью заменяет прежний список."
    )
    pets: list[PetKind] | None = Field(
        None, description="Питомцы в поездке. Полностью заменяет прежний список; [] — без них."
    )
    budget_total_rub: int | None = Field(
        None, gt=0, description="Предельный бюджет на всю группу и всю поездку, ₽."
    )
    cheaper_by_percent: int | None = Field(
        None,
        ge=1,
        le=60,
        description="Сделать поездку дешевле текущей на N процентов. Для просьб «бюджет меньше», "
        "«подешевле» без конкретной суммы; нельзя вместе с budget_total_rub.",
    )
    budget_style: BudgetStyle | None = Field(
        None,
        description="Отношение к цене: economy — «недорого», standard, premium — «лишь бы удобно».",
    )
    max_travel_hours: float | None = Field(
        None, gt=0, description="Предел длительности одного перелёта или поездки, часы."
    )
    min_air_temp_c: int | None = Field(None, description="Минимальная дневная температура, °C.")
    min_sea_temp_c: int | None = Field(None, description="Минимальная температура воды, °C.")
    tags: list[Tag] | None = Field(
        None,
        description="Добавить пожелания к направлению и отелю, включая скрытые потребности "
        "(с детьми — pool, kids_club). Добавляются к уже заданным.",
    )
    drop_tags: list[Tag] | None = Field(None, description="Убрать ранее заданные пожелания.")
    min_stars: int | None = Field(None, ge=1, le=5, description="Минимальная звёздность отеля.")
    meal_plan: MealPlan | None = Field(
        None,
        description="Желаемое питание: RO без питания, BB завтраки, HB полупансион, "
        "FB полный пансион, AI всё включено.",
    )
    max_stops: int | None = Field(
        None,
        ge=0,
        le=2,
        description="Сколько пересадок допустимо в одну сторону: 0 — только прямые рейсы "
        "(«без пересадок»).",
    )
    free_cancellation: bool | None = Field(
        None,
        description="true — только отели с бесплатной отменой; false — снять это требование.",
    )
    transport_kinds: list[TransportKind] | None = Field(
        None,
        min_length=1,
        description="Допустимый транспорт, заменяет прежний список. Только поезд — [train].",
    )
    clear: list[Limit] | None = Field(
        None,
        description="Снять ранее заданные ограничения, названные полями запроса: «неважно, "
        "сколько лететь» — max_travel_hours, «бюджет не ограничен» — budget_total_rub. "
        "Нельзя вместе с заданием того же ограничения.",
    )
    notes: list[str] | None = Field(
        None,
        description="Контекст свободным текстом, который не выражается полями («ребёнок плохо "
        "переносит жару»). Подбор заметки не учитывает: пользуйтесь ими сами, проверяя результаты. "
        "Добавляются к прежним.",
    )
    assumptions: list[str] | None = Field(
        None,
        description="Допущения, сделанные за пользователя, которые надо озвучить ему "
        "(«7 ночей», «ребёнку 7 лет»). Полный актуальный список: заменяет прежний, поэтому "
        "перечислите ещё верные допущения и опустите те, что пользователь уже уточнил.",
    )

    @model_validator(mode="after")
    def _reject_contradictions(self) -> Self:
        if self.shift_days is not None and (self.date_from or self.month):
            raise ValueError("shift_days нельзя сочетать с date_from или month")
        if self.cheaper_by_percent is not None and self.budget_total_rub is not None:
            raise ValueError("cheaper_by_percent нельзя сочетать с budget_total_rub")
        for name in self.clear or []:
            if getattr(self, name) is not None:
                raise ValueError(f"{name} нельзя одновременно задать и снять")
        if "budget_total_rub" in (self.clear or []) and self.cheaper_by_percent is not None:
            raise ValueError("cheaper_by_percent нельзя сочетать со снятием бюджета")
        return self


@dataclass(frozen=True)
class PatchContext:
    """Состояние вне запроса, нужное для относительных изменений («на 2 дня позже»)."""

    current_check_in: date | None = None
    current_total_rub: int | None = None


_PLAIN_FIELDS = {
    "origin",
    "destination",
    "nights",
    "budget_total_rub",
    "budget_style",
    "max_travel_hours",
    "min_air_temp_c",
    "min_sea_temp_c",
    "min_stars",
    "meal_plan",
    "max_stops",
    "free_cancellation",
    "transport_kinds",
}


def apply_patch(request: TripRequest, patch: RequestPatch, context: PatchContext) -> TripRequest:
    """Новый запрос с применёнными изменениями; исходный не меняется."""
    updates: dict[str, Any] = patch.model_dump(include=_PLAIN_FIELDS, exclude_none=True)
    updates |= _date_updates(request, patch, context)
    updates |= _budget_updates(request, patch, context)
    updates |= dict.fromkeys(patch.clear or [])
    updates["party"] = _merged_party(request.party, patch)
    updates["tags"] = _merged_tags(request.tags, patch)
    updates["notes"] = _appended(request.notes, patch.notes)
    updates["assumptions"] = _assumptions(request.assumptions, patch)
    return TripRequest.model_validate({**request.model_dump(), **updates})


def _date_updates(request: TripRequest, patch: RequestPatch, context: PatchContext) -> dict:
    if patch.date_from is not None:
        start = patch.date_from
    elif patch.shift_days:
        base = request.date_from or context.current_check_in
        if base is None:
            raise MissingInformation("Не от чего сдвигать: даты поездки ещё не заданы.")
        start = base + timedelta(days=patch.shift_days)
    elif patch.month is not None:
        return {"month": patch.month, "date_from": None}
    else:
        return {}
    return {"date_from": start, "month": start.month}


def _budget_updates(request: TripRequest, patch: RequestPatch, context: PatchContext) -> dict:
    if patch.cheaper_by_percent is None:
        return {}
    base = context.current_total_rub or request.budget_total_rub
    if base is None:
        return {"budget_style": BudgetStyle.ECONOMY}
    return {"budget_total_rub": round(base * (100 - patch.cheaper_by_percent) / 100, -2)}


def _merged_party(party: Party, patch: RequestPatch) -> Party:
    updates = {
        name: value
        for name in ("adults", "children_ages", "pets")
        if (value := getattr(patch, name)) is not None
    }
    return Party.model_validate({**party.model_dump(), **updates})


def _merged_tags(current: list[Tag], patch: RequestPatch) -> list[Tag]:
    dropped = set(patch.drop_tags or [])
    merged = [tag for tag in current if tag not in dropped]
    merged += [tag for tag in patch.tags or [] if tag not in merged and tag not in dropped]
    return merged


def _assumptions(current: list[str], patch: RequestPatch) -> list[str]:
    """Допущения модели заменяются её новым списком, чтобы устаревшие не копились.

    Допущение о городе вылета по умолчанию записала система: оно остаётся, пока город не назван.
    """
    system = (
        []
        if patch.origin is not None
        else [note for note in current if note.startswith(DEFAULT_ORIGIN_NOTE)]
    )
    model_notes = current if patch.assumptions is None else patch.assumptions
    return system + [note for note in model_notes if not note.startswith(DEFAULT_ORIGIN_NOTE)]


def _appended(current: list[str], extra: list[str] | None) -> list[str]:
    merged = list(current)
    for item in extra or []:
        if item not in merged:
            merged.append(item)
    return merged
