from types import SimpleNamespace
from typing import Any

import openai
import pytest
from openai.types.chat import ChatCompletion

from odin.agent.llm.client import LLMError
from odin.agent.llm.openai_compatible import OpenAICompatibleClient
from odin.agent.llm.types import Message, ToolCall, ToolSpec

TOOL = ToolSpec(
    name="search_hotels",
    description="Найти отели",
    parameters={"type": "object", "properties": {"limit": {"type": "integer"}}},
)


def completion(message: dict[str, Any]) -> ChatCompletion:
    return ChatCompletion.model_validate(
        {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 0,
            "model": "test-model",
            "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
        }
    )


class FakeSDK:
    """Подмена AsyncOpenAI: запоминает запросы и отдаёт заготовленный ответ или ошибку."""

    def __init__(self, response: ChatCompletion | Exception | str) -> None:
        self.requests: list[dict[str, Any]] = []
        self._response = response
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **request: Any) -> ChatCompletion:
        self.requests.append(request)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def client(sdk: FakeSDK, **options: Any) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url="https://llm.example/v1",
        api_key="key",
        model="test-model",
        client=sdk,  # type: ignore[arg-type]
        **options,
    )


def sdk_error(kind: type[openai.OpenAIError], message: str = "boom") -> openai.OpenAIError:
    """Исключение SDK без сетевых деталей: для проверки сообщений достаточно класса."""
    error = kind.__new__(kind)
    Exception.__init__(error, message)
    return error


async def test_conversation_is_sent_in_openai_wire_format() -> None:
    sdk = FakeSDK(completion({"role": "assistant", "content": "Готово"}))
    call = ToolCall(id="call_1", name="search_hotels", arguments='{"limit": 3}')
    messages = [
        Message.system("Ты агент"),
        Message.user("Найди отели"),
        Message.assistant("", [call]),
        Message.tool_result("call_1", '{"options": []}'),
    ]

    await client(sdk).complete(messages, [TOOL])

    request = sdk.requests[0]
    assert request["model"] == "test-model"
    assert request["messages"] == [
        {"role": "system", "content": "Ты агент"},
        {"role": "user", "content": "Найди отели"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "search_hotels", "arguments": '{"limit": 3}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"options": []}'},
    ]
    assert request["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "search_hotels",
                "description": "Найти отели",
                "parameters": TOOL.parameters,
            },
        }
    ]


async def test_temperature_and_tools_are_sent_only_when_set() -> None:
    plain = FakeSDK(completion({"role": "assistant", "content": "ok"}))
    await client(plain).complete([Message.user("привет")], [])
    assert "temperature" not in plain.requests[0]
    assert "tools" not in plain.requests[0]

    tuned = FakeSDK(completion({"role": "assistant", "content": "ok"}))
    await client(tuned, temperature=0.2).complete([Message.user("привет")], [TOOL])
    assert tuned.requests[0]["temperature"] == 0.2
    assert "tools" in tuned.requests[0]


async def test_tool_choice_none_keeps_the_tools_in_the_request() -> None:
    sdk = FakeSDK(completion({"role": "assistant", "content": "итог"}))

    await client(sdk).complete([Message.user("итог")], [TOOL], tool_choice="none")

    request = sdk.requests[0]
    assert request["tool_choice"] == "none"
    assert request["tools"], (
        "часть шлюзов отвергает историю с вызовами, если инструменты не описаны"
    )


async def test_tool_choice_is_not_sent_by_default() -> None:
    sdk = FakeSDK(completion({"role": "assistant", "content": "ok"}))

    await client(sdk).complete([Message.user("привет")], [TOOL])

    assert "tool_choice" not in sdk.requests[0]


async def test_text_reply_is_parsed() -> None:
    sdk = FakeSDK(completion({"role": "assistant", "content": "Здравствуйте!"}))

    reply = await client(sdk).complete([Message.user("привет")], [])

    assert reply.content == "Здравствуйте!"
    assert reply.tool_calls == []


async def test_tool_calls_keep_raw_arguments_and_tolerate_empty_content() -> None:
    sdk = FakeSDK(
        completion(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_9",
                        "type": "function",
                        "function": {"name": "build_plan", "arguments": ""},
                    },
                    {
                        "id": "call_10",
                        "type": "function",
                        "function": {"name": "search_hotels", "arguments": '{"limit": 2}'},
                    },
                ],
            }
        )
    )

    reply = await client(sdk).complete([Message.user("собери")], [TOOL])

    assert reply.content == ""
    assert [(c.id, c.name, c.arguments) for c in reply.tool_calls] == [
        ("call_9", "build_plan", "{}"),
        ("call_10", "search_hotels", '{"limit": 2}'),
    ]


async def test_empty_choices_is_an_explicit_error() -> None:
    empty = ChatCompletion.model_validate(
        {"id": "x", "object": "chat.completion", "created": 0, "model": "m", "choices": []}
    )

    with pytest.raises(LLMError, match="пустой ответ"):
        await client(FakeSDK(empty)).complete([Message.user("привет")], [])


def tool_call_named(name: object, call_id: str = "c1") -> SimpleNamespace:
    function = SimpleNamespace(name=name, arguments="{}")
    return SimpleNamespace(type="function", id=call_id, function=function)


def malformed(message: SimpleNamespace | None) -> ChatCompletion:
    """Ответ, который SDK принял, но в котором нет того, что ждёт клиент."""
    return ChatCompletion.model_construct(choices=[SimpleNamespace(message=message)])


@pytest.mark.parametrize(
    "response",
    [
        "<html>502 Bad Gateway</html>",  # шлюз вернул страницу вместо JSON
        malformed(None),
        malformed(SimpleNamespace(content="", tool_calls=[tool_call_named(None)])),
        malformed(SimpleNamespace(content=["часть", "ответа"], tool_calls=None)),
    ],
    ids=[
        "html instead of json",
        "message is null",
        "tool call without a name",
        "content is a list",
    ],
)
async def test_a_successful_but_malformed_response_is_an_llm_error_with_a_hint(
    response: ChatCompletion | str,
) -> None:
    with pytest.raises(LLMError, match="неожиданном формате"):
        await client(FakeSDK(response)).complete([Message.user("привет")], [])


async def test_missing_and_duplicate_tool_call_ids_are_replaced_by_unique_ones() -> None:
    response = malformed(
        SimpleNamespace(
            content=None,
            tool_calls=[
                tool_call_named("build_plan", ""),
                tool_call_named("check_plan", "dup"),
                tool_call_named("create_cart", "dup"),
            ],
        )
    )

    reply = await client(FakeSDK(response)).complete([Message.user("собери")], [TOOL])

    ids = [call.id for call in reply.tool_calls]
    assert len(set(ids)) == 3
    assert "dup" in ids
    assert all(ids)


@pytest.mark.parametrize(
    ("kind", "hint"),
    [
        (openai.AuthenticationError, "LLM_API_KEY"),
        (openai.PermissionDeniedError, "LLM_API_KEY"),
        (openai.NotFoundError, "LLM_MODEL=test-model"),
        (openai.RateLimitError, "лимит"),
        (openai.APITimeoutError, "LLM_TIMEOUT_SECONDS"),
        (openai.APIConnectionError, "LLM_BASE_URL"),
        (openai.BadRequestError, "tool calling"),
        (openai.InternalServerError, "Ошибка при обращении к LLM"),
    ],
)
async def test_provider_errors_become_actionable_hints(
    kind: type[openai.OpenAIError], hint: str
) -> None:
    sdk = FakeSDK(sdk_error(kind))

    with pytest.raises(LLMError) as error:
        await client(sdk).complete([Message.user("привет")], [])

    assert hint in str(error.value)


@pytest.mark.parametrize("kind", [openai.NotFoundError, openai.APIConnectionError])
async def test_error_hints_never_show_url_credentials(kind: type[openai.OpenAIError]) -> None:
    url = "https://user:s3cret@llm.example:8443/v1?key=TOPSECRET"
    llm = OpenAICompatibleClient(
        base_url=url,
        api_key="key",
        model="test-model",
        client=FakeSDK(sdk_error(kind)),  # type: ignore[arg-type]
    )

    with pytest.raises(LLMError) as error:
        await llm.complete([Message.user("привет")], [])

    hint = str(error.value)
    assert "https://llm.example:8443/v1" in hint
    for secret in ("user:", "s3cret", "TOPSECRET"):
        assert secret not in hint


def test_description_names_the_model_and_host_but_never_url_credentials() -> None:
    llm = OpenAICompatibleClient(
        base_url="https://user:secret@llm.example:8443/v1",
        api_key="key",
        model="test-model",
        client=FakeSDK(completion({"role": "assistant", "content": "ok"})),  # type: ignore[arg-type]
    )

    assert llm.description == "test-model (llm.example)"
