"""Направление и погода по месяцам."""

from pydantic import BaseModel, ConfigDict, Field

from odin.domain.formatting import temperature
from odin.domain.places import Place
from odin.domain.tags import Tag


class Destination(Place):
    description: str
    tags: list[Tag]
    visa_required: bool = False
    entry_note: str = Field("", description="Условия въезда в свободной форме")


class MonthWeather(BaseModel):
    """Типичная погода в месяце (климатическая норма, не прогноз)."""

    model_config = ConfigDict(frozen=True)

    month: int = Field(ge=1, le=12)
    day_c: int
    night_c: int
    sea_c: int | None = Field(None, description="Температура воды; None, если моря нет")
    rain_days: int = Field(ge=0, description="Дней с осадками за месяц")

    def label(self) -> str:
        text = f"днём {temperature(self.day_c)}, ночью {temperature(self.night_c)}"
        if self.sea_c is not None:
            text += f", вода {temperature(self.sea_c)}"
        return f"{text}, дней с осадками: {self.rain_days}"
