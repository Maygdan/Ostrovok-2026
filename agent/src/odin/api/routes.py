"""Маршруты API: проверка состояния, сессии и сообщения."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from odin.api.schemas import ChatReply, Health, MessageIn, SessionState
from odin.api.service import ChatService

router = APIRouter()


def get_chat(request: Request) -> ChatService:
    chat: ChatService = request.app.state.chat
    return chat


Chat = Annotated[ChatService, Depends(get_chat)]


@router.get("/health", summary="Состояние сервиса и режим LLM")
async def health(chat: Chat) -> Health:
    return Health(llm=chat.llm)


@router.post(
    "/sessions",
    status_code=status.HTTP_201_CREATED,
    summary="Начать новый диалог",
)
async def create_session(chat: Chat) -> SessionState:
    return await chat.state(await chat.create_session())


@router.get("/sessions/{session_id}", summary="Состояние диалога: запрос, план, корзина, заказ")
async def get_session(session_id: str, chat: Chat) -> SessionState:
    return await chat.state(chat.get_session(session_id))


@router.post("/sessions/{session_id}/messages", summary="Отправить сообщение агенту")
async def send_message(session_id: str, message: MessageIn, chat: Chat) -> ChatReply:
    result, session = await chat.send(session_id, message.text)
    return ChatReply(reply=result.reply, steps=result.steps, state=await chat.state(session))
