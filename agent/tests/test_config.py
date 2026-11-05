import pytest

from odin.config import Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_TEMPERATURE"):
        monkeypatch.delenv(name, raising=False)


def settings(**env: str) -> Settings:
    return Settings(_env_file=None, **env)  # type: ignore[call-arg]


def test_without_key_llm_is_disabled() -> None:
    loaded = settings()

    assert not loaded.llm_enabled
    assert loaded.llm_base_url == "https://api.deepseek.com"
    assert loaded.llm_model == "deepseek-flash"


def test_blank_key_counts_as_missing() -> None:
    assert not settings(llm_api_key="   ").llm_enabled


def test_key_enables_llm() -> None:
    assert settings(llm_api_key="sk-test").llm_enabled


def test_values_come_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "my-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")

    loaded = settings()

    assert loaded.llm_model == "my-model"
    assert loaded.llm_base_url == "http://localhost:11434/v1"


@pytest.mark.parametrize(
    ("raw", "expected"), [("debug", "DEBUG"), (" Warning ", "WARNING"), ("INFO", "INFO")]
)
def test_log_level_is_case_insensitive(raw: str, expected: str) -> None:
    assert settings(log_level=raw).log_level == expected


def test_unknown_log_level_is_reported_when_settings_load() -> None:
    with pytest.raises(ValueError, match="уровень логов"):
        settings(log_level="loud")


def test_empty_temperature_is_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_TEMPERATURE", "")

    assert settings().llm_temperature is None
