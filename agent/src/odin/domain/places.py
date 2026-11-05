"""Города: пункты вылета и назначения."""

from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field


class Place(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    country: str
    timezone: str = Field(description="IANA-имя часового пояса, например Europe/Moscow")
    lat: float
    lon: float
    airport_code: str
    aliases: list[str] = Field(
        default_factory=list,
        description="Основы названия в нижнем регистре для разбора свободного ввода",
    )

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)
