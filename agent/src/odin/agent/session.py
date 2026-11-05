"""Сессия диалога: запрос, план, корзина, заказ и история сообщений."""

from datetime import date
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from odin.agent.llm.types import Message
from odin.domain.dates import resolve_window
from odin.domain.errors import DomainError
from odin.domain.order import Cart, Order
from odin.domain.places import Place
from odin.domain.plan import Slot, TripPlan
from odin.domain.rebuild import stale_slots
from odin.domain.request import DEFAULT_ORIGIN_NOTE, TripRequest


class Session(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    request: TripRequest = Field(default_factory=TripRequest)
    plan: TripPlan | None = None
    cart: Cart | None = None
    order: Order | None = None
    history: list[Message] = Field(default_factory=list)

    @classmethod
    def start(cls, home: Place) -> "Session":
        """Новая сессия. Город вылета по умолчанию записан как допущение, а не как факт."""
        request = TripRequest(
            origin=home.id,
            assumptions=[f"{DEFAULT_ORIGIN_NOTE}{home.name} — выбран по умолчанию."],
        )
        return cls(request=request)

    def outdated_slots(self, today: date) -> list[Slot]:
        """Какие части плана устарели из-за изменений запроса после последней сборки."""
        if self.plan is None or self.request.destination is None:
            return []
        try:
            window = resolve_window(self.request, today)
        except DomainError:
            return list(Slot)  # например, дата уже прошла: ни один план под запрос не подходит
        stale = stale_slots(self.plan, self.request, window)
        return [slot for slot in Slot if slot in stale]


class SessionStore(Protocol):
    """Хранилище сессий. Сейчас в памяти; для БД достаточно реализовать эти два метода."""

    def get(self, session_id: str) -> Session | None: ...

    def save(self, session: Session) -> None: ...


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def save(self, session: Session) -> None:
        self._sessions[session.id] = session
