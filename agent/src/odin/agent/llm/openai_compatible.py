"""Клиент для любого OpenAI-совместимого API (OpenAI, OpenRouter, vLLM, Ollama и т.п.)."""

from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from odin.agent.llm.client import LLMError
from odin.agent.llm.types import LLMReply, Message, Role, ToolCall, ToolChoice, ToolSpec

UNEXPECTED_REPLY = (
    "LLM вернул ответ в неожиданном формате. Проверьте LLM_BASE_URL: он должен вести "
    "на OpenAI-совместимый API (обычно адрес оканчивается на /v1)."
)


class OpenAICompatibleClient:
    is_demo = False

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float | None = None,
        timeout: float = 60.0,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._client = client or AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self._endpoint = _public_url(base_url)
        self._model = model
        self._temperature = temperature
        self.description = f"{model} ({urlparse(base_url).hostname})"

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        *,
        tool_choice: ToolChoice = "auto",
    ) -> LLMReply:
        request = self._request(messages, tools, tool_choice)
        try:
            response = await self._client.chat.completions.create(**request)
        except openai.OpenAIError as error:
            raise LLMError(self._explain(error)) from error
        try:
            return _parse(response)
        except (AttributeError, TypeError, ValueError, IndexError) as error:
            raise LLMError(UNEXPECTED_REPLY) from error  # «успешный» ответ с чужим телом

    def _request(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec], tool_choice: ToolChoice
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self._model,
            "messages": [_wire_message(message) for message in messages],
        }
        if tools:
            request["tools"] = [_wire_tool(tool) for tool in tools]
            if tool_choice == "none":
                request["tool_choice"] = "none"
        if self._temperature is not None:
            request["temperature"] = self._temperature
        return request

    def _explain(self, error: openai.OpenAIError) -> str:
        """Превращает ошибку SDK в сообщение с подсказкой, что поправить в настройках."""
        match error:
            case openai.AuthenticationError() | openai.PermissionDeniedError():
                return "LLM отклонил ключ доступа. Проверьте LLM_API_KEY в .env."
            case openai.NotFoundError():
                return (
                    f"LLM не нашёл модель или адрес. Проверьте LLM_MODEL={self._model} "
                    f"и LLM_BASE_URL={self._endpoint} в .env."
                )
            case openai.RateLimitError():
                return "Превышен лимит запросов или закончились средства у провайдера LLM."
            case openai.APITimeoutError():
                return "LLM не ответил вовремя. Увеличьте LLM_TIMEOUT_SECONDS или проверьте сеть."
            case openai.APIConnectionError():
                return f"Не удалось подключиться к {self._endpoint}. Проверьте LLM_BASE_URL и сеть."
            case openai.BadRequestError() | openai.UnprocessableEntityError():
                return (
                    f"LLM отклонил запрос: {error}. Убедитесь, что модель {self._model} "
                    "поддерживает вызов функций (tool calling)."
                )
            case _:
                return f"Ошибка при обращении к LLM: {error}"


def _public_url(url: str) -> str:
    """Адрес без логина, пароля и параметров запроса: его можно показывать пользователю."""
    parts = urlparse(url)
    host = parts.hostname or ""
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunparse((parts.scheme, netloc, parts.path, "", "", ""))


def _wire_message(message: Message) -> dict[str, Any]:
    if message.role is Role.TOOL:
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
    wire: dict[str, Any] = {"role": message.role.value, "content": message.content}
    if message.tool_calls:
        wire["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in message.tool_calls
        ]
    return wire


def _wire_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _parse(response: ChatCompletion) -> LLMReply:
    if not isinstance(response, ChatCompletion):  # прокси или шлюз вернул не JSON, а, скажем, HTML
        raise LLMError(UNEXPECTED_REPLY)
    if not response.choices:
        raise LLMError("LLM вернул пустой ответ. Попробуйте ещё раз или смените модель.")
    message = response.choices[0].message
    calls: list[ToolCall] = []
    for call in message.tool_calls or []:
        if call.type == "function":
            call_id = call.id if call.id and all(call.id != c.id for c in calls) else None
            calls.append(
                ToolCall(
                    id=call_id or f"call_{uuid4().hex[:12]}",
                    name=call.function.name,
                    arguments=call.function.arguments or "{}",
                )
            )
    return LLMReply(content=message.content or "", tool_calls=calls)
