"""Погода по месяцам: климатические нормы из climate.json."""

from collections.abc import Mapping
from typing import Self

from pydantic import BaseModel, Field

from odin.domain.destination import Destination, MonthWeather
from odin.providers.mock.files import read_json

Months = Field(min_length=12, max_length=12)


class ClimateRow(BaseModel):
    """Значения по месяцам, январь первым."""

    day_c: list[int] = Months
    night_c: list[int] = Months
    sea_c: list[int] | None = Field(None, min_length=12, max_length=12)
    rain_days: list[int] = Months


class MockWeather:
    def __init__(self, climate: Mapping[str, ClimateRow]) -> None:
        self._climate = climate

    @classmethod
    def from_files(cls) -> Self:
        rows = {
            key: ClimateRow.model_validate(value)
            for key, value in read_json("climate.json").items()
        }
        return cls(rows)

    async def month_weather(self, destination: Destination, month: int) -> MonthWeather | None:
        row = self._climate.get(destination.id)
        if row is None:
            return None
        i = month - 1
        return MonthWeather(
            month=month,
            day_c=row.day_c[i],
            night_c=row.night_c[i],
            sea_c=row.sea_c[i] if row.sea_c else None,
            rain_days=row.rain_days[i],
        )
