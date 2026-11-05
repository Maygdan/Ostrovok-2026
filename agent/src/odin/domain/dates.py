"""Окно поездки: превращает «в ноябре» или точную дату в даты заезда и выезда."""

from dataclasses import dataclass
from datetime import date, timedelta

from odin.domain.errors import DomainError, MissingInformation
from odin.domain.request import TripRequest

DEFAULT_NIGHTS = 7
MIN_LEAD_DAYS = 3  # ближайший вылет — не раньше, чем через столько дней
DEFAULT_START_DAY = 10  # если указан только месяц, вылетаем примерно в его начале


@dataclass(frozen=True)
class DateWindow:
    check_in: date
    check_out: date

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days


def resolve_window(request: TripRequest, today: date) -> DateWindow:
    nights = request.nights or DEFAULT_NIGHTS
    if request.date_from is not None:
        start = request.date_from
        if start < today:
            raise DomainError(f"Дата {start.isoformat()} уже прошла, сегодня {today.isoformat()}.")
    elif request.month is not None:
        start = _start_within_month(request.month, today)
    else:
        raise MissingInformation("Не указаны ни даты, ни месяц поездки.")
    return DateWindow(check_in=start, check_out=start + timedelta(days=nights))


def _start_within_month(month: int, today: date) -> date:
    """Ближайший подходящий вылет в указанном месяце: не раньше MIN_LEAD_DAYS от сегодня."""
    earliest = today + timedelta(days=MIN_LEAD_DAYS)
    year = today.year if month >= today.month else today.year + 1
    start = date(year, month, DEFAULT_START_DAY)
    if start >= earliest:
        return start
    if (earliest.year, earliest.month) == (year, month):
        return earliest  # месяц уже идёт: вылетаем, как только возможно
    return date(year + 1, month, DEFAULT_START_DAY)
