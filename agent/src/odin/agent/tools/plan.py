"""Инструменты плана: сборка и пересборка, ручной выбор варианта, проверка стыковок."""

from typing import Any, Literal

from pydantic import Field

from odin.agent.tools.base import Tool, ToolArgs, ToolContext
from odin.agent.views import diff_view, issue_view, plan_view
from odin.domain.junctions import check_plan as find_issues
from odin.domain.plan import Severity, Slot, TripPlan
from odin.services.planner import BuildResult


class NoArgs(ToolArgs):
    pass


class SelectOptionArgs(ToolArgs):
    part: Literal["outbound", "hotel", "inbound", "transfer_in", "transfer_out"] = Field(
        description="Какую часть плана заменить."
    )
    option_id: str = Field(description="id варианта из результатов search_* или из плана.")


async def build_plan(ctx: ToolContext, args: NoArgs) -> dict[str, Any]:
    ctx.forbid_after_order()
    session = ctx.session
    previous = session.plan
    result = await ctx.planner.build(session.request, previous, ctx.today)
    return _adopt(ctx, result, rebuilt=previous is not None)


async def select_option(ctx: ToolContext, args: SelectOptionArgs) -> dict[str, Any]:
    ctx.forbid_after_order()
    plan = ctx.require_plan()
    forced = {Slot(args.part): args.option_id}
    result = await ctx.planner.build(ctx.session.request, plan, ctx.today, forced=forced)
    return _adopt(ctx, result, rebuilt=True)


async def check_plan(ctx: ToolContext, args: NoArgs) -> dict[str, Any]:
    plan = ctx.require_plan()
    issues = find_issues(plan)
    result: dict[str, Any] = {
        "issues": [issue_view(issue) for issue in issues],
        "ready_for_cart": _ready(plan),
        "summary": f"Проблем: {len(issues)}, из них блокирующих: {len(plan.errors)}",
    }
    outdated = ctx.session.outdated_slots(ctx.today)
    if outdated:
        result["plan_outdated_parts"] = [slot.value for slot in outdated]
        result["next"] = "Запрос изменился после сборки плана: вызовите build_plan."
    return result


def _adopt(ctx: ToolContext, result: BuildResult, *, rebuilt: bool) -> dict[str, Any]:
    """Принимает собранный план в сессию. Корзина от прежней ревизии плана больше не верна."""
    session = ctx.session
    session.plan = result.plan
    notes = list(result.notes)
    if session.cart is not None and session.cart.plan_revision != result.plan.revision:
        session.cart = None
        notes.append("Прежняя корзина сброшена: план изменился.")
    output: dict[str, Any] = {
        "plan": plan_view(result.plan),
        "ready_for_cart": _ready(result.plan),
        "recomputed_parts": [slot.value for slot in Slot if slot in result.recomputed],
        "summary": _summary(result.plan, rebuilt),
    }
    if rebuilt:
        output["changes"] = diff_view(result.diff)
    if notes:
        output["notes"] = notes
    return output


def _ready(plan: TripPlan) -> bool:
    return not plan.errors and not plan.missing_slots


def _summary(plan: TripPlan, rebuilt: bool) -> str:
    verb = "пересобран" if rebuilt else "собран"
    problems = sum(issue.severity is not Severity.INFO for issue in plan.issues)
    return (
        f"План {verb} (ревизия {plan.revision}): {plan.destination.name}, "
        f"{plan.check_in.isoformat()}…{plan.check_out.isoformat()}, "
        f"итого {plan.total_price_rub} ₽, предупреждений и ошибок: {problems}"
    )


TOOLS = [
    Tool(
        name="build_plan",
        description=(
            "Собрать план поездки (дорога туда и обратно, отель, трансферы) для выбранного "
            "направления или пересобрать его после изменения запроса. Пересчитываются только "
            "затронутые части, прежний выбор сохраняется, пока он подходит. Возвращает план с "
            "объяснением каждого выбора (pros — почему подходит, cons — чем пожертвовано, risks — "
            "риски), проблемы стыковок (issues) и что изменилось (changes)."
        ),
        arguments=NoArgs,
        handler=build_plan,
    ),
    Tool(
        name="select_option",
        description=(
            "Заменить выбранный вариант в плане на тот, который назвал пользователь (id из "
            "результатов search_* или плана). Выбор пользователя закрепляется и сохраняется при "
            "дальнейших пересборках, пока вариант доступен."
        ),
        arguments=SelectOptionArgs,
        handler=select_option,
    ),
    Tool(
        name="check_plan",
        description=(
            "Перепроверить стыковки плана: прилёт и заселение, трансферы, выселение и вылет, "
            "пересадки, питомцы, вместимость номера, бюджет. Вызывайте перед корзиной."
        ),
        arguments=NoArgs,
        handler=check_plan,
    ),
]
