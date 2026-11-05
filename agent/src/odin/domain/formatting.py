"""Форматирование сумм, дат и длительностей для объяснений на русском языке."""

from datetime import date, datetime

NBSP = "\N{NO-BREAK SPACE}"

MONTHS_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)  # fmt: skip
MONTHS_PREPOSITIONAL = (
    "январе", "феврале", "марте", "апреле", "мае", "июне",
    "июле", "августе", "сентябре", "октябре", "ноябре", "декабре",
)  # fmt: skip


def rub(amount: int) -> str:
    """118400 -> '118 400 ₽' (неразрывные пробелы, чтобы сумма не переносилась)."""
    return f"{amount:,}".replace(",", NBSP) + f"{NBSP}₽"


def signed_rub(amount: int) -> str:
    """+1100 -> '+1 100 ₽', -900 -> '−900 ₽' (с настоящим минусом)."""
    sign = "+" if amount >= 0 else "\N{MINUS SIGN}"
    return sign + rub(abs(amount))


def temperature(celsius: int) -> str:
    """22 -> '+22°C', 0 -> '0°C', -5 -> '−5°C' (с настоящим минусом)."""
    if celsius == 0:
        return "0°C"
    sign = "+" if celsius > 0 else "\N{MINUS SIGN}"
    return f"{sign}{abs(celsius)}°C"


def plural(n: int, one: str, few: str, many: str) -> str:
    """Склонение по числу: 1 ночь, 2 ночи, 5 ночей."""
    n = abs(n)
    if 11 <= n % 100 <= 14:
        return many
    if n % 10 == 1:
        return one
    return few if 2 <= n % 10 <= 4 else many


def nights(n: int) -> str:
    return f"{n} {plural(n, 'ночь', 'ночи', 'ночей')}"


def duration(minutes: int) -> str:
    """225 -> '3 ч 45 мин'."""
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours} ч {mins} мин"
    return f"{hours} ч" if hours else f"{mins} мин"


def hours(value: float) -> str:
    """4.4 -> '4,4 ч' (для грубых оценок времени в пути)."""
    return f"{value:.1f}".replace(".", ",").removesuffix(",0") + " ч"


def clock(moment: datetime) -> str:
    return moment.strftime("%H:%M")


def day_month(day: date) -> str:
    return f"{day.day} {MONTHS_GENITIVE[day.month - 1]}"


def date_range(start: date, end: date) -> str:
    """14–21 ноября или 28 ноября – 5 декабря."""
    if start.month == end.month:
        return f"{start.day}–{end.day} {MONTHS_GENITIVE[end.month - 1]}"
    return f"{day_month(start)} – {day_month(end)}"


def km(value: float) -> str:
    """12.0 -> '12 км', 1.5 -> '1,5 км'."""
    return f"{value:.1f}".replace(".", ",").removesuffix(",0") + " км"


def distance(meters: int) -> str:
    """150 -> '150 м', 1200 -> '1,2 км'."""
    return km(meters / 1000) if meters >= 1000 else f"{meters} м"
