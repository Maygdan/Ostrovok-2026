"""Интерфейс клиента LLM. Любой провайдер, умеющий tool calling, подключается реализацией."""

from collections.abc import Sequence
from typing import Protocol

from odin.agent.llm.types import LLMReply, Message, ToolChoice, ToolSpec


class LLMError(Exception):
    """Не удалось получить ответ от LLM. Сообщение содержит подсказку, что исправить."""


class LLMClient(Protocol):
    description: str  # человекочитаемо: какая модель отвечает
    is_demo: bool  # True, если это заглушка, а не настоящая модель

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        *,
        tool_choice: ToolChoice = "auto",
    ) -> LLMReply:
        """Один шаг диалога: модель отвечает текстом или просит вызвать инструменты.

        Инструменты передаются и при tool_choice="none": в истории уже есть их вызовы, а часть
        шлюзов отвергает такую историю без описания инструментов.
        """
        ...
