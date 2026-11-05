"""Инструмент агента, его контекст и реестр с безопасным исполнением."""

import json
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from odin.agent.llm.types import ToolCall, ToolSpec
from odin.agent.session import Session
from odin.agent.tools.schema import tool_parameters
from odin.domain.errors import DomainError, MissingInformation
from odin.domain.plan import TripPlan
from odin.providers.interfaces import Providers
from odin.services.checkout import CheckoutService
from odin.services.planner import TripPlanner

logger = logging.getLogger(__name__)


class ToolError(Exception):
    """Инструмент нельзя выполнить сейчас. Текст возвращается модели, чтобы она исправилась."""


class ToolArgs(BaseModel):
    """База аргументов инструментов: неизвестные поля отвергаются, чтобы модель исправилась."""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ToolContext:
    session: Session
    providers: Providers
    planner: TripPlanner
    checkout: CheckoutService
    today: date

    def require_plan(self) -> TripPlan:
        if self.session.plan is None:
            raise ToolError("План ещё не собран: сначала вызовите build_plan.")
        return self.session.plan

    def require_current_plan(self) -> TripPlan:
        """План, соответствующий запросу: после изменения запроса его нужно пересобрать."""
        plan = self.require_plan()
        if self.session.outdated_slots(self.today):
            raise ToolError("План устарел после изменения запроса. Сначала вызовите build_plan.")
        return plan

    def forbid_after_order(self) -> None:
        if self.session.order is not None:
            raise ToolError(
                "Заказ уже оформлен. Изменения после покупки пока не поддерживаются; "
                "для новой поездки нужен новый диалог."
            )


type Handler = Callable[[ToolContext, Any], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    arguments: type[BaseModel]
    handler: Handler

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=tool_parameters(self.arguments),
        )


class AgentStep(BaseModel):
    """Один вызов инструмента: что вызвали, чем закончилось. Видно в интерфейсе и логах."""

    tool: str
    arguments: dict[str, Any]
    ok: bool
    summary: str
    duration_ms: int
    choices: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Структурированные варианты направления для кнопок выбора в чате",
    )


@dataclass(frozen=True)
class ToolOutcome:
    content: str  # JSON для модели
    step: AgentStep


class ToolRegistry:
    def __init__(self, tools: Sequence[Tool]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def specs(self) -> list[ToolSpec]:
        return [tool.spec() for tool in self._tools.values()]

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        """Выполняет вызов. Любая ошибка превращается в результат, который увидит модель."""
        started = time.perf_counter()
        arguments: dict[str, Any] = {}
        try:
            tool = self._tools.get(call.name)
            if tool is None:
                known = ", ".join(self._tools)
                raise ToolError(f"Нет инструмента «{call.name}». Доступны: {known}.")
            arguments = _decode(call.arguments)
            result = await tool.handler(context, tool.arguments.model_validate(arguments))
            ok = True
        except ValidationError as error:
            result, ok = {"error": f"Неверные аргументы: {_describe(error)}"}, False
        except MissingInformation as error:
            result, ok = {"error": str(error), "ask_user": True}, False
        except (ToolError, DomainError) as error:
            result, ok = {"error": str(error)}, False
        except Exception:
            logger.exception("Сбой инструмента %s", call.name)
            result, ok = {"error": "Внутренняя ошибка инструмента. Попробуйте иначе."}, False
        summary = str(result.get("summary") or result.get("error") or "готово")
        raw_choices = result.get("options")
        choices = (
            raw_choices
            if call.name == "search_destinations"
            and ok
            and isinstance(raw_choices, list)
            and all(isinstance(choice, dict) for choice in raw_choices)
            else []
        )
        choices = choices[:4]
        step = AgentStep(
            tool=call.name,
            arguments=arguments,
            ok=ok,
            summary=summary,
            duration_ms=round((time.perf_counter() - started) * 1000),
            choices=choices,
        )
        logger.info("tool %s ok=%s %s", call.name, ok, summary)
        return ToolOutcome(json.dumps(result, ensure_ascii=False, default=str), step)


def _decode(raw: str) -> dict[str, Any]:
    try:
        decoded = json.loads(raw or "{}")
    except json.JSONDecodeError as error:
        raise ToolError(f"Аргументы не являются корректным JSON: {error}.") from error
    if not isinstance(decoded, dict):
        raise ToolError("Аргументы должны быть JSON-объектом.")
    return decoded


def _describe(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc']) or 'аргументы'}: {item['msg']}"
        for item in error.errors()
    )
