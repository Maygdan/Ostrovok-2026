"""Инструменты поиска и сравнения: направления, отели, рейсы и поезда, трансферы."""

from typing import Any, Literal

from pydantic import Field

from odin.agent.tools.base import Tool, ToolArgs, ToolContext
from odin.agent.views import destination_view, ranked_view
from odin.domain.plan import Slot


class LimitArgs(ToolArgs):
    limit: int = Field(5, ge=1, le=10, description="Сколько лучших вариантов вернуть.")


class TransportArgs(LimitArgs):
    direction: Literal["outbound", "inbound"] = Field(
        description="outbound — дорога туда, inbound — обратно."
    )


class TransferArgs(LimitArgs):
    direction: Literal["in", "out"] = Field(
        description="in — из аэропорта или с вокзала в отель, out — из отеля обратно."
    )


async def search_destinations(ctx: ToolContext, args: LimitArgs) -> dict[str, Any]:
    found = await ctx.planner.search.destinations(ctx.session.request, ctx.today)
    result: dict[str, Any] = {
        "check_in": found.window.check_in.isoformat(),
        "check_out": found.window.check_out.isoformat(),
        "options": [destination_view(item) for item in found.ranked[: args.limit]],
        "excluded": [
            {"name": item.destination.name, "reason": item.reason} for item in found.excluded
        ],
        "summary": f"Подходящих направлений: {len(found.ranked)}, отсеяно: {len(found.excluded)}",
    }
    if not found.ranked:
        result["hint"] = "Ничего не подошло. Предложите смягчить условия: бюджет, дорогу, даты."
    return result


async def search_hotels(ctx: ToolContext, args: LimitArgs) -> dict[str, Any]:
    trip = await ctx.planner.search.resolve_trip(ctx.session.request, ctx.today)
    found = await ctx.planner.search.hotels(trip)
    return {
        "check_in": trip.window.check_in.isoformat(),
        "check_out": trip.window.check_out.isoformat(),
        "options": [ranked_view(item) for item in found.ranked[: args.limit]],
        "filtered_out": found.reasons,
        "summary": f"Подходящих тарифов отелей: {len(found.ranked)}",
    }


async def search_transport(ctx: ToolContext, args: TransportArgs) -> dict[str, Any]:
    slot = Slot.OUTBOUND if args.direction == "outbound" else Slot.INBOUND
    trip = await ctx.planner.search.resolve_trip(ctx.session.request, ctx.today)
    found = await ctx.planner.search.transport(trip, slot)
    return {
        "options": [ranked_view(item) for item in found.ranked[: args.limit]],
        "filtered_out": found.reasons,
        "summary": f"Подходящих рейсов и поездов: {len(found.ranked)}",
    }


async def search_transfers(ctx: ToolContext, args: TransferArgs) -> dict[str, Any]:
    plan = ctx.require_plan()
    arriving = args.direction == "in"
    slot = Slot.TRANSFER_IN if arriving else Slot.TRANSFER_OUT
    transport = plan.outbound if arriving else plan.inbound
    if transport is None or plan.hotel is None:
        return {"error": "В плане нет рейса или отеля: сначала соберите план (build_plan)."}
    trip = await ctx.planner.search.resolve_trip(plan.built_for, ctx.today)
    found = await ctx.planner.search.transfers(trip, slot, transport, plan.hotel)
    return {
        "options": [ranked_view(item) for item in found.ranked[: args.limit]],
        "filtered_out": found.reasons,
        "summary": f"Подходящих трансферов: {len(found.ranked)}",
    }


TOOLS = [
    Tool(
        name="search_destinations",
        description=(
            "Подобрать и сравнить направления под текущий запрос: цена «от», погода в месяц "
            "поездки, время в пути, плюсы, минусы и причины, по которым остальные направления "
            "отброшены. Нужны город вылета и месяц или даты."
        ),
        arguments=LimitArgs,
        handler=search_destinations,
    ),
    Tool(
        name="search_hotels",
        description=(
            "Показать и сравнить тарифы отелей в выбранном направлении на даты поездки: цена, "
            "питание, условия отмены, расположение, плюсы, минусы и риски. Нужно направление."
        ),
        arguments=LimitArgs,
        handler=search_hotels,
    ),
    Tool(
        name="search_transport",
        description=(
            "Показать и сравнить рейсы и поезда туда (outbound) или обратно (inbound): цена, "
            "время в пути, пересадки, время суток, багаж, возвратность. Нужно направление."
        ),
        arguments=TransportArgs,
        handler=search_transport,
    ),
    Tool(
        name="search_transfers",
        description=(
            "Показать трансферы между аэропортом или вокзалом и отелем под время выбранного "
            "рейса: in — в отель, out — из отеля. Нужен собранный план."
        ),
        arguments=TransferArgs,
        handler=search_transfers,
    ),
]
