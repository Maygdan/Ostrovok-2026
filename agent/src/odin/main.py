"""Точка входа: сборка приложения из настроек и запуск сервера."""

import logging
import mimetypes
from collections.abc import Callable
from datetime import date
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from odin.agent.llm.client import LLMClient, LLMError
from odin.agent.llm.factory import build_llm
from odin.agent.loop import Agent
from odin.agent.session import InMemorySessionStore, SessionStore
from odin.agent.tools import default_tools
from odin.agent.tools.base import ToolRegistry
from odin.api.routes import router
from odin.api.service import ChatService, SessionNotFound
from odin.config import Settings
from odin.domain.errors import DomainError
from odin.providers.interfaces import Providers
from odin.providers.mock import build_mock_providers

logger = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "web"

# На Windows реестр иногда отдаёт .js как text/plain, и браузер не загружает модули страницы.
mimetypes.add_type("text/javascript", ".js")


def create_app(
    settings: Settings | None = None,
    *,
    llm: LLMClient | None = None,
    providers: Providers | None = None,
    store: SessionStore | None = None,
    clock: Callable[[], date] = date.today,
) -> FastAPI:
    """Собирает приложение. `llm`, `providers`, `store` и `clock` можно подменить в тестах."""
    settings = settings or Settings()
    llm = llm or build_llm(settings)
    providers = providers or build_mock_providers()
    agent = Agent(
        llm,
        ToolRegistry(default_tools()),
        providers,
        max_steps=settings.agent_max_steps,
        clock=clock,
    )
    if llm.is_demo:
        logger.warning("LLM_API_KEY не задан: работает демо-режим без LLM (правила вместо модели)")
    else:
        logger.info("LLM: %s", llm.description)

    app = FastAPI(
        title="О!дин запрос: ИИ-агент для путешествий",
        description="Прототип. Данные об отелях, рейсах и ценах синтетические.",
    )
    sessions = store or InMemorySessionStore()
    app.state.chat = ChatService(agent, sessions, providers, settings.default_origin)
    app.include_router(router, prefix="/api")
    _register_error_handlers(app)
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(SessionNotFound)
    async def session_not_found(request: Request, error: SessionNotFound) -> JSONResponse:
        return JSONResponse({"detail": "Диалог не найден: начните новый."}, status_code=404)

    @app.exception_handler(LLMError)
    async def llm_failed(request: Request, error: LLMError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=502)

    @app.exception_handler(DomainError)
    async def misconfigured(request: Request, error: DomainError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=500)


def run() -> None:
    settings = Settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    uvicorn.run("odin.main:create_app", factory=True, host=settings.host, port=settings.port)
