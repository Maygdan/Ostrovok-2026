import asyncio
import re
from collections.abc import Sequence

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from odin.agent.llm.client import LLMError
from odin.agent.llm.stub import StubLLM
from odin.agent.llm.types import LLMReply, Message, ToolCall, ToolSpec
from odin.agent.session import InMemorySessionStore, Session
from odin.config import Settings
from odin.main import create_app
from tests.agent.helpers import ScriptedLLM
from tests.conftest import TODAY

HEADLINE = "Хочу к тёплому морю в сентябре, недорого, с ребёнком, без долгих перелётов"


def make_app(llm=None, **settings) -> FastAPI:
    return create_app(
        Settings(_env_file=None, **settings), llm=llm or StubLLM(), clock=lambda: TODAY
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(make_app())


def new_session(client: TestClient) -> str:
    response = client.post("/api/sessions")
    assert response.status_code == 201
    return response.json()["session_id"]


def say(client: TestClient, session_id: str, text: str) -> dict:
    response = client.post(f"/api/sessions/{session_id}/messages", json={"text": text})
    assert response.status_code == 200, response.text
    return response.json()


class TestSessions:
    def test_health_reports_the_demo_mode(self, client: TestClient) -> None:
        body = client.get("/api/health").json()

        assert body["status"] == "ok"
        assert body["llm"]["is_demo"] is True

    def test_new_session_starts_with_the_default_origin_as_an_assumption(
        self, client: TestClient
    ) -> None:
        body = client.post("/api/sessions").json()

        assert body["request"]["origin"] == "moscow"
        assert any("по умолчанию" in a for a in body["request"]["assumptions"])
        assert body["plan"] is None
        assert body["transcript"] == []

    def test_session_can_be_read_back(self, client: TestClient) -> None:
        session_id = new_session(client)
        say(client, session_id, HEADLINE)

        body = client.get(f"/api/sessions/{session_id}").json()

        assert body["session_id"] == session_id
        assert [e["role"] for e in body["transcript"]] == ["user", "assistant"]
        assert body["request"]["month"] == 9

    def test_unknown_session_is_a_404_with_a_human_message(self, client: TestClient) -> None:
        for response in (
            client.get("/api/sessions/nope"),
            client.post("/api/sessions/nope/messages", json={"text": "привет"}),
        ):
            assert response.status_code == 404
            assert "начните новый" in response.json()["detail"]

    def test_sessions_are_independent(self, client: TestClient) -> None:
        first, second = new_session(client), new_session(client)

        say(client, first, HEADLINE)

        assert client.get(f"/api/sessions/{second}").json()["request"]["month"] is None

    def test_unknown_default_origin_is_reported_with_a_hint(self) -> None:
        client = TestClient(make_app(default_origin="atlantis"))

        response = client.post("/api/sessions")

        assert response.status_code == 500
        assert "DEFAULT_ORIGIN=atlantis" in response.json()["detail"]


class TestMessages:
    def test_first_message_returns_destinations_steps_and_state(self, client: TestClient) -> None:
        session_id = new_session(client)

        body = say(client, session_id, HEADLINE)

        assert "Подходящие направления" in body["reply"]
        assert [s["tool"] for s in body["steps"]] == ["update_trip_request", "search_destinations"]
        assert all(step["ok"] for step in body["steps"])
        choices = body["steps"][1]["choices"]
        assert 2 <= len(choices) <= 4
        assert {"id", "name", "country", "price_from_rub", "weather", "travel_time"} <= set(
            choices[0]
        )
        assert body["state"]["request"]["party"]["children_ages"] == [7]
        assert body["state"]["plan"] is None

    def test_whole_journey_over_http(self, client: TestClient) -> None:
        session_id = new_session(client)
        say(client, session_id, HEADLINE)

        planned = say(client, session_id, "Давай первый вариант")["state"]
        plan = planned["plan"]
        assert plan["total_price_rub"] > 0
        assert plan["revision"] == 1
        assert {"outbound", "hotel", "inbound", "transfer_in", "transfer_out"} <= set(plan)
        assert plan["explanations"]["hotel"]["pros"]

        later = say(client, session_id, "А можно на два дня позже?")["state"]
        assert later["plan"]["revision"] == 2
        assert later["plan"]["check_in"] > plan["check_in"]
        assert later["outdated_parts"] == []

        carted = say(client, session_id, "Оформляй")["state"]
        assert carted["cart"]["presented"] is True
        assert carted["order"] is None

        paid = say(client, session_id, "Оплачиваю")["state"]
        assert paid["order"]["total_price_rub"] == later["plan"]["total_price_rub"]
        assert len(paid["order"]["bookings"]) == 5
        assert paid["cart"]["status"] == "paid"

    def test_changed_request_marks_the_plan_as_outdated_until_rebuilt(self) -> None:
        llm = ScriptedLLM(
            LLMReply(
                tool_calls=[
                    ToolCall.of("update_trip_request", month=11, destination="Анапа"),
                    ToolCall.of("build_plan"),
                ]
            ),
            LLMReply(content="План готов"),
            LLMReply(tool_calls=[ToolCall.of("update_trip_request", pets=["dog"])]),
            LLMReply(content="Записал, но пока не пересобрал"),
            LLMReply(tool_calls=[ToolCall.of("build_plan")]),
            LLMReply(content="Пересобрал"),
        )
        client = TestClient(make_app(llm=llm))
        session_id = new_session(client)
        say(client, session_id, "Хочу в Анапу в ноябре")

        after_change = say(client, session_id, "С нами будет собака")["state"]
        after_rebuild = say(client, session_id, "Пересобери")["state"]

        assert set(after_change["outdated_parts"]) == {
            "outbound", "hotel", "inbound", "transfer_in", "transfer_out"
        }  # fmt: skip
        assert after_rebuild["outdated_parts"] == []
        assert after_rebuild["plan"]["hotel"]["hotel"]["pets_allowed"] is True

    @pytest.mark.parametrize("payload", [{"text": ""}, {"text": "   "}, {"text": "я" * 4001}, {}])
    def test_invalid_messages_are_rejected_before_reaching_the_agent(
        self, client: TestClient, payload: dict
    ) -> None:
        session_id = new_session(client)

        response = client.post(f"/api/sessions/{session_id}/messages", json=payload)

        assert response.status_code == 422
        assert client.get(f"/api/sessions/{session_id}").json()["transcript"] == []

    def test_surrounding_whitespace_is_trimmed(self, client: TestClient) -> None:
        session_id = new_session(client)

        say(client, session_id, f"   {HEADLINE}\n")

        transcript = client.get(f"/api/sessions/{session_id}").json()["transcript"]
        assert transcript[0]["text"] == HEADLINE


class FailingLLM:
    description = "сломанная модель"
    is_demo = False

    async def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> LLMReply:
        raise LLMError("LLM отклонил ключ доступа. Проверьте LLM_API_KEY в .env.")


class TestTranscript:
    def test_restored_dialogue_shows_only_what_the_chat_showed(self) -> None:
        llm = ScriptedLLM(
            LLMReply(
                content="Сейчас всё подберу…",
                tool_calls=[ToolCall.of("update_trip_request", month=11)],
            ),
            LLMReply(content="Записал: ноябрь."),
        )
        client = TestClient(make_app(llm=llm))
        session_id = new_session(client)
        say(client, session_id, "Хочу в ноябре")

        transcript = client.get(f"/api/sessions/{session_id}").json()["transcript"]

        assert [(entry["role"], entry["text"]) for entry in transcript] == [
            ("user", "Хочу в ноябре"),
            ("assistant", "Записал: ноябрь."),
        ]


class TestLLMFailures:
    def test_llm_error_is_a_502_with_the_actionable_hint(self) -> None:
        client = TestClient(make_app(llm=FailingLLM()))
        session_id = new_session(client)

        response = client.post(f"/api/sessions/{session_id}/messages", json={"text": "Привет"})

        assert response.status_code == 502
        assert "LLM_API_KEY" in response.json()["detail"]

    def test_failed_turn_leaves_no_trace_in_the_dialogue(self) -> None:
        client = TestClient(make_app(llm=FailingLLM()))
        session_id = new_session(client)
        client.post(f"/api/sessions/{session_id}/messages", json={"text": "Привет"})

        body = client.get(f"/api/sessions/{session_id}").json()

        assert body["transcript"] == []
        assert body["llm"] == {"description": "сломанная модель", "is_demo": False}


class RecordingStore(InMemorySessionStore):
    """Хранилище, которое запоминает, в каком виде сессию сохраняли."""

    def __init__(self) -> None:
        super().__init__()
        self.saved: list[Session] = []

    def save(self, session: Session) -> None:
        super().save(session)
        self.saved.append(session.model_copy(deep=True))


class TestUnexpectedFailures:
    def test_what_the_turn_already_changed_is_saved_even_if_the_turn_breaks(self) -> None:
        llm = ScriptedLLM(
            LLMReply(tool_calls=[ToolCall.of("update_trip_request", month=11)]),
            RuntimeError("что-то пошло не так"),
        )
        store = RecordingStore()
        app = create_app(Settings(_env_file=None), llm=llm, store=store, clock=lambda: TODAY)
        client = TestClient(app, raise_server_exceptions=False)
        session_id = new_session(client)

        response = client.post(f"/api/sessions/{session_id}/messages", json={"text": "в ноябре"})

        assert response.status_code == 500
        assert store.saved[-1].request.month == 11


class ProbeLLM:
    """Следит за тем, сколько обращений к модели идёт одновременно."""

    description = "probe"
    is_demo = False

    def __init__(self) -> None:
        self.active = 0
        self.peak = 0

    async def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> LLMReply:
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.02)
        self.active -= 1
        return LLMReply(content="ok")


class TestConcurrency:
    async def burst(self, app: FastAPI, session_ids: list[str]) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            await asyncio.gather(
                *(
                    http.post(f"/api/sessions/{sid}/messages", json={"text": "привет"})
                    for sid in session_ids
                )
            )

    async def create(self, app: FastAPI, count: int) -> list[str]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            responses = [await http.post("/api/sessions") for _ in range(count)]
        return [r.json()["session_id"] for r in responses]

    async def test_double_submit_in_one_session_is_processed_one_at_a_time(self) -> None:
        probe = ProbeLLM()
        app = make_app(llm=probe)
        (session_id,) = await self.create(app, 1)

        await self.burst(app, [session_id, session_id, session_id])

        assert probe.peak == 1

    async def test_different_sessions_do_not_block_each_other(self) -> None:
        probe = ProbeLLM()
        app = make_app(llm=probe)
        sessions = await self.create(app, 3)

        await self.burst(app, sessions)

        assert probe.peak > 1


class TestWebUi:
    def test_chat_page_is_served_from_the_root(self, client: TestClient) -> None:
        response = client.get("/")

        assert response.status_code == 200
        assert "О!дин запрос" in response.text

    def test_openapi_describes_the_api(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]

        assert "/api/sessions/{session_id}/messages" in paths
        assert "/api/health" in paths

    def test_every_script_and_stylesheet_the_page_needs_is_served(self, client: TestClient) -> None:
        page = client.get("/").text
        assets = set(re.findall(r'(?:src|href)="([^"#]+)"', page))
        for name in list(assets):
            if name.endswith(".js"):
                assets |= set(re.findall(r'from "\./([^"]+)"', client.get(f"/{name}").text))

        assert {"app.js", "style.css"} <= assets
        for name in assets:
            response = client.get(f"/{name}")
            assert response.status_code == 200, name
            if name.endswith(".js"):
                assert "javascript" in response.headers["content-type"], name
