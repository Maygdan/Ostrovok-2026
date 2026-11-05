"""Сводка понимания запроса для интерфейса: готовые подписи вместо сырых полей."""

from odin.api.schemas import Chip
from odin.domain.destination import Destination
from odin.domain.formatting import (
    MONTHS_PREPOSITIONAL,
    day_month,
    hours,
    nights,
    rub,
    temperature,
)
from odin.domain.hotel import MEAL_LABELS
from odin.domain.places import Place
from odin.domain.request import BudgetStyle, TripRequest
from odin.domain.tags import TAG_LABELS
from odin.domain.transport import TransportKind

BUDGET_WORDS = {BudgetStyle.ECONOMY: "недорого", BudgetStyle.PREMIUM: "комфорт важнее цены"}
TRANSPORT_WORDS = {TransportKind.TRAIN: "только поезд", TransportKind.FLIGHT: "только самолёт"}


def summarize(
    request: TripRequest, origin: Place | None, destination: Destination | None
) -> list[Chip]:
    """Что агент понял о поездке, в порядке «откуда, куда, когда, с кем, чего хочется»."""
    chips: list[Chip] = []
    if origin:
        chips.append(Chip(label="Откуда", value=origin.name))
    if destination:
        chips.append(Chip(label="Куда", value=destination.name))
    if when := _when(request):
        chips.append(Chip(label="Когда", value=when))
    chips.append(Chip(label="Кто едет", value=request.party.label()))
    if request.budget_total_rub:
        chips.append(Chip(label="Бюджет", value=f"до {rub(request.budget_total_rub)}"))
    elif request.budget_style in BUDGET_WORDS:
        chips.append(Chip(label="Бюджет", value=BUDGET_WORDS[request.budget_style]))
    if request.max_travel_hours:
        chips.append(Chip(label="В пути", value=f"до {hours(request.max_travel_hours)}"))
    if request.min_sea_temp_c is not None:
        chips.append(Chip(label="Вода", value=f"от {temperature(request.min_sea_temp_c)}"))
    if request.min_air_temp_c is not None:
        chips.append(Chip(label="Воздух", value=f"от {temperature(request.min_air_temp_c)}"))
    if request.min_stars:
        chips.append(Chip(label="Отель", value=f"от {request.min_stars}★"))
    if request.meal_plan:
        chips.append(Chip(label="Питание", value=MEAL_LABELS[request.meal_plan]))
    if request.free_cancellation:
        chips.append(Chip(label="Отмена", value="бесплатная отмена отеля"))
    if request.max_stops is not None:
        stops = "без пересадок" if request.max_stops == 0 else f"не больше {request.max_stops}"
        chips.append(Chip(label="Пересадки", value=stops))
    if len(request.transport_kinds) == 1:
        chips.append(Chip(label="Транспорт", value=TRANSPORT_WORDS[request.transport_kinds[0]]))
    if request.tags:
        wishes = ", ".join(TAG_LABELS[tag] for tag in request.tags)
        chips.append(Chip(label="Пожелания", value=wishes))
    return chips


def _when(request: TripRequest) -> str | None:
    if request.date_from:
        value = f"с {day_month(request.date_from)}"
    elif request.month:
        value = f"в {MONTHS_PREPOSITIONAL[request.month - 1]}"
    else:
        return None
    return f"{value}, {nights(request.nights)}" if request.nights else value
