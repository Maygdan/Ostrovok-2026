"""Сервис диалогов: сессии, ход агента с блокировкой на сессию, снимок состояния."""

import asyncio
from collections import defaultdict

from odin.agent.llm.types import Role
from odin.agent.loop import Agent, TurnResult
from odin.agent.session import Session, SessionStore
from odin.api.schemas import LlmInfo, SessionState, TranscriptEntry
from odin.api.summary import summarize
from odin.domain.errors import DomainError
from odin.providers.interfaces import Providers


class SessionNotFound(Exception):
    pass


class ChatService:
    def __init__(
        self, agent: Agent, store: SessionStore, providers: Providers, default_origin: str
    ) -> None:
        self._agent = agent
        self._store = store
        self._providers = providers
        self._default_origin = default_origin
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    @property
    def llm(self) -> LlmInfo:
        return LlmInfo(description=self._agent.llm.description, is_demo=self._agent.llm.is_demo)

    async def create_session(self) -> Session:
        home = await self._providers.catalog.get_place(self._default_origin)
        if home is None:
            raise DomainError(
                f"DEFAULT_ORIGIN={self._default_origin} нет в каталоге городов. Проверьте .env."
            )
        session = Session.start(home)
        self._store.save(session)
        return session

    def get_session(self, session_id: str) -> Session:
        session = self._store.get(session_id)
        if session is None:
            raise SessionNotFound(session_id)
        return session

    async def send(self, session_id: str, text: str) -> tuple[TurnResult, Session]:
        """Один ход. Два сообщения в одну сессию не обрабатываются одновременно."""
        session = self.get_session(session_id)
        async with self._locks[session_id]:
            try:
                result = await self._agent.respond(session, text)
            finally:
                self._store.save(session)  # состояние могло измениться и при сбое хода
        return result, session

    async def state(self, session: Session) -> SessionState:
        catalog = self._providers.catalog
        request = session.request
        origin = await catalog.get_place(request.origin) if request.origin else None
        destination = (
            await catalog.get_destination(request.destination) if request.destination else None
        )
        return SessionState(
            session_id=session.id,
            llm=self.llm,
            request=request,
            summary=summarize(request, origin, destination),
            plan=session.plan,
            outdated_parts=session.outdated_slots(self._agent.clock()),
            cart=session.cart,
            order=session.order,
            transcript=_transcript(session),
        )


def _transcript(session: Session) -> list[TranscriptEntry]:
    """Реплики, которые видел пользователь: его сообщения и итоговые ответы агента.

    Реплики модели рядом с вызовами инструментов («сейчас подберу…») в чате не показываются.
    """
    return [
        TranscriptEntry(role=message.role, text=message.content)
        for message in session.history
        if message.content
        and not message.tool_calls
        and message.role in (Role.USER, Role.ASSISTANT)
    ]
