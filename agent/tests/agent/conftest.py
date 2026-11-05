import json
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from odin.agent.llm.stub import StubLLM
from odin.agent.llm.types import ToolCall
from odin.agent.loop import Agent
from odin.agent.session import Session
from odin.agent.tools import default_tools
from odin.agent.tools.base import ToolContext, ToolRegistry
from odin.providers.interfaces import Providers
from odin.services.checkout import CheckoutService
from odin.services.planner import TripPlanner
from tests.agent.helpers import Conversation
from tests.conftest import TODAY

ToolRunner = Callable[..., Awaitable[dict[str, Any]]]


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry(default_tools())


@pytest.fixture
async def session(providers: Providers) -> Session:
    home = await providers.catalog.get_place("moscow")
    assert home is not None
    return Session.start(home)


@pytest.fixture
def context(session: Session, providers: Providers) -> ToolContext:
    return ToolContext(
        session=session,
        providers=providers,
        planner=TripPlanner(providers),
        checkout=CheckoutService(providers),
        today=TODAY,
    )


@pytest.fixture
def run(registry: ToolRegistry, context: ToolContext) -> ToolRunner:
    """Вызывает инструмент как агент и возвращает результат, который увидела бы модель."""

    async def runner(name: str, **arguments: Any) -> dict[str, Any]:
        outcome = await registry.execute(ToolCall.of(name, **arguments), context)
        return json.loads(outcome.content)

    return runner


@pytest.fixture
def conversation(providers: Providers, session: Session) -> Conversation:
    """Диалог с агентом на демо-заглушке: весь путь на моках, без доступа к LLM."""
    agent = Agent(StubLLM(), ToolRegistry(default_tools()), providers, clock=lambda: TODAY)
    return Conversation(agent, session)
