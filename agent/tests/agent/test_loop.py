import pytest

from odin.agent.llm.client import LLMError
from odin.agent.llm.types import LLMReply, Role, ToolCall
from odin.agent.loop import EMPTY_REPLY, Agent
from odin.agent.session import Session
from odin.agent.tools import default_tools
from odin.agent.tools.base import ToolRegistry
from odin.providers.interfaces import Providers
from tests.agent.helpers import ScriptedLLM
from tests.conftest import TODAY


def agent_with(llm: ScriptedLLM, providers: Providers, **options) -> Agent:
    return Agent(llm, ToolRegistry(default_tools()), providers, clock=lambda: TODAY, **options)


def text(content: str) -> LLMReply:
    return LLMReply(content=content)


def calls(*tool_calls: ToolCall) -> LLMReply:
    return LLMReply(tool_calls=list(tool_calls))


async def test_plain_answer_ends_the_turn(providers: Providers, session: Session) -> None:
    llm = ScriptedLLM(text("Здравствуйте! Куда поедем?"))

    result = await agent_with(llm, providers).respond(session, "Привет")

    assert result.reply == "Здравствуйте! Куда поедем?"
    assert result.steps == []
    assert [m.role for m in session.history] == [Role.USER, Role.ASSISTANT]


async def test_tool_results_go_back_to_the_model_in_openai_order(
    providers: Providers, session: Session
) -> None:
    call = ToolCall.of("update_trip_request", month=11)
    llm = ScriptedLLM(calls(call), text("Записал: ноябрь."))

    result = await agent_with(llm, providers).respond(session, "Хочу в ноябре")

    assert result.reply == "Записал: ноябрь."
    messages, _ = llm.requests[1]
    assert [m.role for m in messages] == [Role.SYSTEM, Role.USER, Role.ASSISTANT, Role.TOOL]
    assert messages[2].tool_calls[0].id == call.id
    assert messages[3].tool_call_id == call.id
    assert '"month": 11' in messages[3].content
    assert [step.tool for step in result.steps] == ["update_trip_request"]
    assert session.request.month == 11


async def test_every_request_carries_tools_and_fresh_state(
    providers: Providers, session: Session
) -> None:
    llm = ScriptedLLM(calls(ToolCall.of("update_trip_request", month=11)), text("ок"))

    await agent_with(llm, providers).respond(session, "Хочу в ноябре")

    (first, tools), (second, _) = llm.requests
    assert {tool.name for tool in tools} == {tool.name for tool in default_tools()}
    assert "Сегодня: 2026-10-28, среда" in first[0].content
    assert '"month"' not in first[0].content
    assert '"month": 11' in second[0].content, "состояние в промпте обновляется после инструментов"


async def test_several_tool_calls_in_one_reply_run_in_order(
    providers: Providers, session: Session
) -> None:
    llm = ScriptedLLM(
        calls(
            ToolCall.of("update_trip_request", month=11, destination="Анапа"),
            ToolCall.of("build_plan"),
        ),
        text("План готов"),
    )

    result = await agent_with(llm, providers).respond(session, "Сразу в Анапу")

    assert [s.tool for s in result.steps] == ["update_trip_request", "build_plan"]
    assert all(step.ok for step in result.steps)
    assert session.plan is not None


async def test_failed_call_is_shown_to_the_model_which_fixes_it(
    providers: Providers, session: Session
) -> None:
    llm = ScriptedLLM(
        calls(ToolCall.of("update_trip_request", month=13)),
        calls(ToolCall.of("update_trip_request", month=12)),
        text("Исправил"),
    )

    result = await agent_with(llm, providers).respond(session, "В тринадцатом месяце")

    assert [step.ok for step in result.steps] == [False, True]
    error_message = llm.requests[1][0][-1]
    assert error_message.role is Role.TOOL
    assert "month" in error_message.content
    assert session.request.month == 12


async def test_step_limit_forces_a_final_answer_but_keeps_the_tools_declared(
    providers: Providers, session: Session
) -> None:
    loop = calls(ToolCall.of("update_trip_request", month=11))
    llm = ScriptedLLM(loop, loop, text("Остановился, вот итог"))

    result = await agent_with(llm, providers, max_steps=2).respond(session, "зациклись")

    assert result.reply == "Остановился, вот итог"
    assert len(llm.requests) == 3
    assert llm.tool_choices == ["auto", "auto", "none"]
    assert llm.requests[-1][1], "в истории есть вызовы инструментов, значит, их описания нужны"


async def test_tool_calls_in_the_forced_final_answer_are_not_kept_in_the_history(
    providers: Providers, session: Session
) -> None:
    loop = calls(ToolCall.of("update_trip_request", month=11))
    stubborn = calls(ToolCall.of("build_plan"))  # модель игнорирует tool_choice="none"
    llm = ScriptedLLM(loop, stubborn)

    result = await agent_with(llm, providers, max_steps=1).respond(session, "зациклись")

    assert result.reply == EMPTY_REPLY
    last = session.history[-1]
    assert last.role is Role.ASSISTANT
    assert last.tool_calls == [], "иначе каждый следующий запрос нарушит порядок вызовов и ответов"


async def test_empty_model_answer_is_replaced_with_a_polite_fallback(
    providers: Providers, session: Session
) -> None:
    result = await agent_with(ScriptedLLM(text("")), providers).respond(session, "алло")

    assert result.reply == EMPTY_REPLY
    assert session.history[-1].content == EMPTY_REPLY, "пустая реплика не должна попасть в историю"


async def test_llm_failure_leaves_the_dialogue_untouched(
    providers: Providers, session: Session
) -> None:
    llm = ScriptedLLM(LLMError("LLM отклонил ключ"))

    with pytest.raises(LLMError):
        await agent_with(llm, providers).respond(session, "Привет")

    assert session.history == []


async def test_failure_after_actions_keeps_the_history_consistent_with_the_state(
    providers: Providers, session: Session
) -> None:
    llm = ScriptedLLM(
        text("Первый ход"),
        calls(ToolCall.of("update_trip_request", month=11)),
        LLMError("сеть пропала"),
    )
    agent = agent_with(llm, providers)
    await agent.respond(session, "Привет")

    result = await agent.respond(session, "Хочу в ноябре")

    assert session.request.month == 11, "действие выполнено"
    assert [m.role for m in session.history[2:]] == [
        Role.USER,
        Role.ASSISTANT,
        Role.TOOL,
        Role.ASSISTANT,
    ], "сообщение пользователя, вызов, результат и пояснение — модель увидит, что было сделано"
    assert "сеть пропала" in result.reply
    assert "что получилось" in result.reply
    assert [step.tool for step in result.steps] == ["update_trip_request"]
    assert session.history[-1].content == result.reply


async def test_cart_created_in_a_turn_the_model_failed_is_not_counted_as_shown(
    providers: Providers, session: Session
) -> None:
    create = calls(
        ToolCall.of("update_trip_request", month=11, destination="Анапа"),
        ToolCall.of("build_plan"),
        ToolCall.of("create_cart"),
    )
    llm = ScriptedLLM(create, LLMError("таймаут"))

    await agent_with(llm, providers).respond(session, "Хочу в Анапу и оформи")

    assert session.cart is not None
    assert not session.cart.presented, "пользователь не видел ответа модели с корзиной"


async def test_order_paid_in_a_turn_the_model_failed_is_not_lost(
    providers: Providers, session: Session
) -> None:
    create = calls(
        ToolCall.of("update_trip_request", month=11, destination="Анапа"),
        ToolCall.of("build_plan"),
        ToolCall.of("create_cart"),
    )
    pay = calls(ToolCall.of("pay_cart", confirmed=True))
    llm = ScriptedLLM(create, text("Вот корзина, подтверждаете?"), pay, LLMError("таймаут"))
    agent = agent_with(llm, providers)
    await agent.respond(session, "Хочу в Анапу и оформи")

    result = await agent.respond(session, "Оплачиваю")

    assert session.order is not None
    assert [step.tool for step in result.steps] == ["pay_cart"]
    assert "таймаут" in result.reply


async def test_cart_counts_as_shown_only_after_the_turn_that_created_it(
    providers: Providers, session: Session
) -> None:
    create = [
        ToolCall.of("update_trip_request", month=11, destination="Анапа", children_ages=[7]),
        ToolCall.of("build_plan"),
        ToolCall.of("create_cart"),
        ToolCall.of("pay_cart", confirmed=True),  # модель поторопилась в том же ходу
    ]
    llm = ScriptedLLM(calls(*create), text("Вот корзина, подтвердите оплату"))
    agent = agent_with(llm, providers)

    first = await agent.respond(session, "Хочу в Анапу, сразу оформи и оплати")

    pay_step = first.steps[-1]
    assert pay_step.tool == "pay_cart"
    assert not pay_step.ok
    assert session.order is None
    assert session.cart is not None
    assert session.cart.presented, "после ответа пользователь корзину увидел"

    llm2 = ScriptedLLM(calls(ToolCall.of("pay_cart", confirmed=True)), text("Оплачено"))
    second = await agent_with(llm2, providers).respond(session, "Да, оплачиваю")

    assert second.steps[0].ok
    assert session.order is not None
