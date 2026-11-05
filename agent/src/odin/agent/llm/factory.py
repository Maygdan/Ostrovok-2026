"""Выбор клиента LLM по настройкам: настоящая модель при наличии ключа, иначе демо-заглушка."""

from odin.agent.llm.client import LLMClient
from odin.agent.llm.openai_compatible import OpenAICompatibleClient
from odin.agent.llm.stub import StubLLM
from odin.config import Settings


def build_llm(settings: Settings) -> LLMClient:
    if settings.llm_api_key is None or not settings.llm_enabled:
        return StubLLM()
    return OpenAICompatibleClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value(),
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_seconds,
    )
