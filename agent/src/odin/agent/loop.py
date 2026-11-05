"""Цикл агента: модель просит инструменты, мы их выполняем и возвращаем результаты."""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from odin.agent.llm.client import LLMClient, LLMError
from odin.agent.llm.types import Message
from odin.agent.prompts import SYSTEM_PROMPT, render_state
from odin.agent.session import Session
from odin.agent.tools.base import AgentStep, ToolContext, ToolRegistry
from odin.providers.interfaces import Providers
from odin.services.checkout import CheckoutService
from odin.services.planner import TripPlanner

logger = logging.getLogger(__name__)

EMPTY_REPLY = "Не получилось сформулировать ответ. Повторите, пожалуйста, или уточните запрос."
DESTINATION_MENTION = re.compile(
    r"\b(?:в|во|на)\s+([А-ЯЁа-яё][А-ЯЁа-яё-]+(?:\s+[А-ЯЁа-яё][А-ЯЁа-яё-]+)?)",
    re.IGNORECASE,
)
NON_DESTINATIONS = {
    "автобус",
    "дн",
    "ден",
    "город",
    "гор",
    "машин",
    "месяц",
    "мест",
    "мор",
    "направлен",
    "отпуск",
    "поезд",
    "путешеств",
    "природ",
    "курорт",
    "недел",
    "самолет",
    "сут",
    "такси",
    "выходн",
}


@dataclass(frozen=True)
class TurnResult:
    reply: str
    steps: list[AgentStep]


def _finish(session: Session, content: str) -> str:
    """Записывает итоговую реплику; пустой ответ модели заменяется пояснением."""
    text = content or EMPTY_REPLY
    session.history.append(Message.assistant(text))
    return text


def _after_failure(error: LLMError) -> str:
    return (
        f"Действия по вашему сообщению выполнены, но ответ сформулировать не удалось: {error} "
        "Напишите «что получилось?», и я расскажу."
    )


class Agent:
    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        providers: Providers,
        *,
        max_steps: int = 12,
        clock: Callable[[], date] = date.today,
    ) -> None:
        self.llm = llm
        self.clock = clock
        self._tools = tools
        self._providers = providers
        self._planner = TripPlanner(providers)
        self._checkout = CheckoutService(providers)
        self._max_steps = max_steps

    async def respond(self, session: Session, user_text: str) -> TurnResult:
        """Один ход диалога.

        Если модель недоступна до первого действия, ход откатывается целиком: можно повторить
        то же сообщение. Если действия уже выполнены (запрос изменён, план собран, заказ
        оплачен), история сохраняется, чтобы она не расходилась с состоянием, а вместо ответа
        модели пользователь получает пояснение. Корзина при этом не считается показанной.
        """
        mark = len(session.history)
        session.history.append(Message.user(user_text))
        steps: list[AgentStep] = []
        if destination := await self._unsupported_destination(user_text):
            reply = (
                f"Направления «{destination}» пока нет в каталоге. Хотите, я покажу "
                "доступные варианты? Без вашего согласия подменять город не буду."
            )
            session.history.append(Message.assistant(reply))
            return TurnResult(reply, steps)
        try:
            reply = await self._run(session, steps)
        except LLMError as error:
            if not steps:
                del session.history[mark:]
                raise
            logger.warning("Модель недоступна после действий агента: %s", error)
            reply = _after_failure(error)
            session.history.append(Message.assistant(reply))
            return TurnResult(reply, steps)
        if session.cart is not None and not session.cart.presented:
            session.cart = session.cart.mark_presented()
        return TurnResult(reply, steps)

    async def _unsupported_destination(self, text: str) -> str | None:
        for match in DESTINATION_MENTION.finditer(text):
            candidate = match.group(1).strip()
            words = candidate.lower().replace("ё", "е").split()
            if await self._providers.catalog.find_destination(candidate) is not None:
                return None
            if any(word.startswith(stem) for word in words for stem in NON_DESTINATIONS):
                continue
            if re.fullmatch(
                r"(?:январ\w*|феврал\w*|март\w*|апрел\w*|ма[еяю]\w*|июн\w*|июл\w*|"
                r"август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)",
                words[0],
            ):
                continue
            return candidate
        return None

    async def _run(self, session: Session, steps: list[AgentStep]) -> str:
        today = self.clock()
        context = ToolContext(session, self._providers, self._planner, self._checkout, today)
        specs = self._tools.specs()
        for _ in range(self._max_steps):
            reply = await self.llm.complete(self._messages(session, today), specs)
            if not reply.tool_calls:
                return _finish(session, reply.content)
            session.history.append(reply.as_message())
            for call in reply.tool_calls:
                outcome = await self._tools.execute(call, context)
                session.history.append(Message.tool_result(call.id, outcome.content))
                steps.append(outcome.step)
        logger.warning("Лимит шагов %s исчерпан, запрашиваем итоговый ответ", self._max_steps)
        final = await self.llm.complete(self._messages(session, today), specs, tool_choice="none")
        return _finish(session, final.content)

    @staticmethod
    def _messages(session: Session, today: date) -> list[Message]:
        system = f"{SYSTEM_PROMPT}\n\n{render_state(session, today)}"
        return [Message.system(system), *session.history]
