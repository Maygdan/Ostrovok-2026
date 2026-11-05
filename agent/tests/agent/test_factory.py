from odin.agent.llm.factory import build_llm
from odin.agent.llm.openai_compatible import OpenAICompatibleClient
from odin.agent.llm.stub import StubLLM
from odin.config import Settings


def settings(**env: str) -> Settings:
    return Settings(_env_file=None, **env)  # type: ignore[arg-type]


def test_without_a_key_the_demo_stub_is_used() -> None:
    llm = build_llm(settings())

    assert isinstance(llm, StubLLM)
    assert llm.is_demo


def test_blank_key_is_the_same_as_no_key() -> None:
    assert isinstance(build_llm(settings(llm_api_key="  ")), StubLLM)


def test_with_a_key_a_real_provider_is_configured_from_settings() -> None:
    llm = build_llm(
        settings(
            llm_api_key="sk-test",
            llm_model="my-model",
            llm_base_url="http://localhost:11434/v1",
        )
    )

    assert isinstance(llm, OpenAICompatibleClient)
    assert not llm.is_demo
    assert llm.description == "my-model (localhost)"
