"""Помощники для тестов диалога: сценарная LLM и обёртка над агентом."""

from collections.abc import Sequence

from odin.agent.llm.types import LLMReply, Message, ToolChoice, ToolSpec
from odin.agent.loop import Agent
from odin.agent.session import Session
from odin.agent.tools.base import AgentStep


class ScriptedLLM:
    """LLM, отвечающая заранее заготовленными репликами; запоминает всё, что ей отправили."""

    description = "сценарная LLM для тестов"
    is_demo = False

    def __init__(self, *replies: LLMReply | Exception) -> None:
        self._replies = list(replies)
        self.requests: list[tuple[list[Message], list[ToolSpec]]] = []
        self.tool_choices: list[ToolChoice] = []

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        *,
        tool_choice: ToolChoice = "auto",
    ) -> LLMReply:
        self.requests.append((list(messages), list(tools)))
        self.tool_choices.append(tool_choice)
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class Conversation:
    """Диалог пользователя с агентом: говорим фразу — получаем ответ и шаги агента."""

    def __init__(self, agent: Agent, session: Session) -> None:
        self.agent = agent
        self.session = session
        self.steps: list[AgentStep] = []

    async def say(self, text: str) -> str:
        result = await self.agent.respond(self.session, text)
        self.steps = result.steps
        return result.reply

    @property
    def tools_used(self) -> list[str]:
        return [step.tool for step in self.steps]
