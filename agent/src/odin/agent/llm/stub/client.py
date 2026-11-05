"""Заглушка LLM для демо без ключа и для тестов.

Это не модель: по тексту пользователя она выбирает действия по простым правилам, вызывает те же
инструменты, что и настоящая модель, и формулирует ответ по их результатам. Она нужна, чтобы
весь путь от запроса до имитации оплаты можно было пройти и проверить без доступа к LLM.
"""

import re
from collections.abc import Sequence
from typing import Any

from odin.agent.llm.stub import replies
from odin.agent.llm.stub.dialogue import Dialogue
from odin.agent.llm.stub.understanding import normalize, understand, wants_cart, wants_payment
from odin.agent.llm.types import LLMReply, Message, ToolCall, ToolChoice, ToolSpec

DEFAULT_NIGHTS_NOTE = "Срок поездки не назван — подбираю на 7 ночей."


class StubLLM:
    description = "демо-заглушка без LLM (правила вместо модели)"
    is_demo = True

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        *,
        tool_choice: ToolChoice = "auto",
    ) -> LLMReply:
        """Правила не зацикливаются на инструментах, поэтому tool_choice ей не нужен."""
        dialogue = Dialogue(messages)
        if dialogue.turn:  # инструменты этого хода уже отработали — формулируем ответ
            return LLMReply(content=replies.compose(dialogue))
        return self._act(dialogue)

    def _act(self, dialogue: Dialogue) -> LLMReply:
        text = normalize(dialogue.user_text)
        if dialogue.ordered:
            return LLMReply(content=replies.ALREADY_ORDERED)
        if dialogue.cart_open and wants_payment(text):
            return _calls(ToolCall.of("pay_cart", confirmed=True))
        if dialogue.plan_built:
            return self._after_plan(dialogue, text)
        return self._before_plan(dialogue, text)

    def _after_plan(self, dialogue: Dialogue, text: str) -> LLMReply:
        if wants_cart(text) or wants_payment(text):
            return _calls(ToolCall.of("create_cart"))
        patch = understand(text)
        if not patch:
            return LLMReply(content=replies.HELP)
        patch = _with_assumptions(patch, dialogue)
        return _calls(ToolCall.of("update_trip_request", **patch), ToolCall.of("build_plan"))

    def _before_plan(self, dialogue: Dialogue, text: str) -> LLMReply:
        if re.search(r"помощь|справк|что ты умеешь|что умеешь", text):
            return LLMReply(content=replies.HELP)
        if chosen := dialogue.chosen_destination():
            return _calls(
                ToolCall.of("update_trip_request", destination=chosen), ToolCall.of("build_plan")
            )
        patch = understand(text)
        if not patch:
            return LLMReply(content=replies.NOT_UNDERSTOOD)
        if "nights" not in patch:
            patch["assumptions"] = [*patch.get("assumptions", []), DEFAULT_NIGHTS_NOTE]
        patch = _with_assumptions(patch, dialogue)
        return _calls(
            ToolCall.of("update_trip_request", **patch), ToolCall.of("search_destinations")
        )


def _with_assumptions(patch: dict[str, Any], dialogue: Dialogue) -> dict[str, Any]:
    """update_trip_request заменяет список допущений, поэтому прежние верные нужно повторить."""
    current = dialogue.assumptions()
    if "nights" in patch:
        current = [note for note in current if note != DEFAULT_NIGHTS_NOTE]
    merged = [*current, *(note for note in patch.get("assumptions", []) if note not in current)]
    return {**patch, "assumptions": merged} if merged != dialogue.assumptions() else patch


def _calls(*calls: ToolCall) -> LLMReply:
    return LLMReply(tool_calls=list(calls))
