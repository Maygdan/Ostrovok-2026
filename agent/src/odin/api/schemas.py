"""Схемы HTTP-запросов и ответов."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from odin.agent.llm.types import Role
from odin.agent.tools.base import AgentStep
from odin.domain.order import Cart, Order
from odin.domain.plan import Slot, TripPlan
from odin.domain.request import TripRequest


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000, description="Сообщение пользователя")

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("сообщение пустое")
        return value


class TranscriptEntry(BaseModel):
    role: Role = Field(description="user или assistant")
    text: str


class Chip(BaseModel):
    """Одна подпись понимания запроса: «Когда — в ноябре, 7 ночей»."""

    label: str
    value: str


class LlmInfo(BaseModel):
    description: str
    is_demo: bool


class SessionState(BaseModel):
    """Всё, что нужно интерфейсу, чтобы показать диалог, понимание запроса, план и заказ."""

    session_id: str
    llm: LlmInfo
    request: TripRequest
    summary: list[Chip] = Field(description="Что агент понял о поездке, в виде готовых подписей")
    plan: TripPlan | None
    outdated_parts: list[Slot] = Field(
        description="Части плана, устаревшие после изменения запроса"
    )
    cart: Cart | None
    order: Order | None
    transcript: list[TranscriptEntry]


class ChatReply(BaseModel):
    reply: str
    steps: list[AgentStep] = Field(description="Что агент делал, прежде чем ответить")
    state: SessionState


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    llm: LlmInfo
