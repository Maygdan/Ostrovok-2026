"""Типы обмена с LLM. Не зависят от SDK конкретного провайдера."""

import json
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import uuid4

from pydantic import BaseModel, Field

type ToolChoice = Literal["auto", "none"]
"""«auto» — модель сама решает, звать ли инструменты; «none» — только текстовый ответ."""


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolCall(BaseModel):
    """Вызов инструмента, как его вернула модель. Аргументы — JSON-строка без разбора."""

    id: str
    name: str
    arguments: str = "{}"

    @classmethod
    def of(cls, name: str, **arguments: Any) -> Self:
        """Собирает вызов из обычных аргументов (для заглушки и тестов)."""
        encoded = json.dumps(arguments, ensure_ascii=False, default=str)
        return cls(id=f"call_{uuid4().hex[:12]}", name=name, arguments=encoded)


class Message(BaseModel):
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None

    @classmethod
    def system(cls, content: str) -> Self:
        return cls(role=Role.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> Self:
        return cls(role=Role.USER, content=content)

    @classmethod
    def assistant(cls, content: str = "", tool_calls: list[ToolCall] | None = None) -> Self:
        return cls(role=Role.ASSISTANT, content=content, tool_calls=tool_calls or [])

    @classmethod
    def tool_result(cls, call_id: str, content: str) -> Self:
        return cls(role=Role.TOOL, content=content, tool_call_id=call_id)


class ToolSpec(BaseModel):
    """Описание инструмента для модели: имя, назначение, JSON Schema параметров."""

    name: str
    description: str
    parameters: dict[str, Any]


class LLMReply(BaseModel):
    """Ответ модели: текст, вызовы инструментов или и то и другое."""

    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)

    def as_message(self) -> Message:
        return Message.assistant(self.content, self.tool_calls)
