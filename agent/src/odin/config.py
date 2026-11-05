"""Настройки приложения: переменные окружения и файл .env."""

import logging

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_api_key: SecretStr | None = None
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-flash"
    llm_temperature: float | None = None
    llm_timeout_seconds: float = 60.0

    agent_max_steps: int = Field(12, ge=1)
    default_origin: str = "moscow"

    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def _level_name(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in logging.getLevelNamesMapping():
            raise ValueError(f"неизвестный уровень логов {value!r}: DEBUG, INFO, WARNING, ERROR")
        return level

    @field_validator("llm_temperature", mode="before")
    @classmethod
    def _empty_temperature_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def llm_enabled(self) -> bool:
        """Есть ли ключ LLM. Без него приложение работает в демо-режиме с заглушкой."""
        return bool(self.llm_api_key and self.llm_api_key.get_secret_value().strip())
