"""Инструмент записи понимания запроса: явные пожелания, скрытые потребности, изменения."""

from typing import Any

from odin.agent.tools.base import Tool, ToolContext, ToolError
from odin.agent.views import request_view
from odin.domain.dates import resolve_window
from odin.domain.errors import DomainError
from odin.domain.rebuild import changed_fields
from odin.domain.request import PatchContext, RequestPatch, apply_patch


class UpdateTripRequestArgs(RequestPatch):
    """Те же поля, что у изменения запроса; города можно называть по-русски."""


async def update_trip_request(ctx: ToolContext, args: UpdateTripRequestArgs) -> dict[str, Any]:
    ctx.forbid_after_order()
    patch = await _with_resolved_cities(ctx, args)
    session = ctx.session
    before = session.request
    session.request = apply_patch(before, patch, _patch_context(ctx))
    changed = sorted(changed_fields(before, session.request))
    result: dict[str, Any] = {
        "request": request_view(session.request),
        "missing": session.request.missing,
        "summary": "Запрос обновлён: " + ", ".join(changed) if changed else "Запрос не изменился",
    }
    outdated = session.outdated_slots(ctx.today)
    if outdated:
        result["plan_outdated_parts"] = [slot.value for slot in outdated]
        result["next"] = "План устарел. Вызовите build_plan: он пересоберёт только эти части."
    return result


async def _with_resolved_cities(ctx: ToolContext, args: RequestPatch) -> RequestPatch:
    catalog = ctx.providers.catalog
    updates: dict[str, str] = {}
    if args.origin is not None:
        origin = await catalog.find_place(args.origin)
        if origin is None:
            known = ", ".join(place.name for place in await catalog.list_places())
            raise ToolError(f"Неизвестный город вылета «{args.origin}». Известные города: {known}.")
        updates["origin"] = origin.id
    if args.destination is not None:
        destination = await catalog.find_destination(args.destination)
        if destination is None:
            known = ", ".join(d.name for d in await catalog.list_destinations())
            raise ToolError(
                f"Направления «{args.destination}» нет в базе. Доступные направления: {known}."
            )
        updates["destination"] = destination.id
    return args.model_copy(update=updates)


def _patch_context(ctx: ToolContext) -> PatchContext:
    """Даты и цена текущего плана — опора для относительных просьб («на 2 дня позже»)."""
    plan = ctx.session.plan
    if plan is not None:
        return PatchContext(current_check_in=plan.check_in, current_total_rub=plan.total_price_rub)
    try:
        check_in = resolve_window(ctx.session.request, ctx.today).check_in
    except DomainError:
        check_in = None
    return PatchContext(current_check_in=check_in)


TOOLS = [
    Tool(
        name="update_trip_request",
        description=(
            "Записать или изменить то, что вы поняли о запросе пользователя: явные пожелания и "
            "скрытые потребности (с ребёнком, с питомцем, бюджет, ограничения по времени в пути). "
            "Передавайте только изменившиеся поля. Вызывайте при каждом новом факте и при каждом "
            "изменении условий («на два дня позже», «бюджет меньше», «с нами собака»). "
            "Возвращает актуальный запрос, чего не хватает для поиска и какие части плана устарели."
        ),
        arguments=UpdateTripRequestArgs,
        handler=update_trip_request,
    )
]
