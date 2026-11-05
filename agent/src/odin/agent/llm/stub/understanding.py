"""Разбор свободного текста правилами. Понимает типовые формулировки, но не язык вообще.

Настоящая модель делает это сама; здесь — ровно столько, чтобы демо-сценарий работал без ключа.
"""

import re
from datetime import date
from typing import Any

MONTH_STEMS = (
    ("январ", 1), ("феврал", 2), ("март", 3), ("апрел", 4), ("мая", 5), ("мае", 5),
    ("июн", 6), ("июл", 7), ("август", 8), ("сентябр", 9), ("октябр", 10), ("ноябр", 11),
    ("декабр", 12),
)  # fmt: skip
NUMBER_WORDS = {
    "один": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5,
    "шесть": 6, "семь": 7, "неделю": 1, "день": 1, "сутки": 1,
}  # fmt: skip
DEFAULT_CHILD_AGE = 7
NUMBER = r"\d+|" + "|".join(NUMBER_WORDS)
SHIFT_PATTERNS = (
    rf"(?:на\s+)?(?P<n>{NUMBER})\s*(?P<unit>дн\w*|день|недел\w*|сут\w*)?\s*(?P<way>позже|раньше)",
    rf"(?P<way>позже|раньше)\s+на\s+(?P<n>{NUMBER})\s*(?P<unit>дн\w*|день|недел\w*|сут\w*)?",
)


def normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


def understand(text: str) -> dict[str, Any]:
    """Поля update_trip_request, которые удалось найти в тексте. Пусто — ничего не поняли."""
    text = normalize(text)
    patch: dict[str, Any] = {}
    assumptions: list[str] = []
    patch.update(_dates(text))
    patch.update(_party(text, assumptions))
    patch.update(_budget(text))
    patch.update(_preferences(text))
    patch.update(_changes(text))
    if "cheaper_by_percent" in patch:  # относительная просьба вытесняет абсолютные поля бюджета
        patch.pop("budget_style", None)
        patch.pop("budget_total_rub", None)
    if assumptions:
        patch["assumptions"] = assumptions
    return patch


def _dates(text: str) -> dict[str, Any]:
    if _shift_days(text) is not None:
        return {}  # «на два дня позже» — сдвиг, а не новый срок или месяц
    explicit_dates = re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if explicit_dates:
        found = {"date_from": explicit_dates[0]}
        if len(explicit_dates) > 1:
            found["nights"] = (
                date.fromisoformat(explicit_dates[1]) - date.fromisoformat(explicit_dates[0])
            ).days
        elif nights := re.search(r"(\d+)\s*(?:ноч|дн|сут)", text):
            found["nights"] = int(nights.group(1))
        return found
    found: dict[str, Any] = {}
    if month := next((number for stem, number in MONTH_STEMS if stem in text), None):
        found["month"] = month
    if nights := re.search(r"(\d+)\s*(?:ноч|дн|сут)", text):
        found["nights"] = int(nights.group(1))
    elif "две недели" in text:
        found["nights"] = 14
    elif "недел" in text:
        found["nights"] = 7
    elif "выходн" in text:
        found["nights"] = 2
    return found


def _party(text: str, assumptions: list[str]) -> dict[str, Any]:
    found: dict[str, Any] = {}
    if adults := re.search(r"\b(\d+)\s+взросл", text):
        found["adults"] = int(adults.group(1))
    children = re.search(r"\b(\d+)\s+(?:дет\w*|ребен\w*)", text)
    if re.search(r"без\s+(?:детей|ребен)", text):
        found["children_ages"] = []
    elif children and int(children.group(1)) == 0:
        found["children_ages"] = []
    elif re.search(r"ребен|дет(?:ьми|ей|и)\b|дочк|сын\b|сыном|малыш", text):
        listed = re.search(r"((?:\d{1,2}\s*(?:,|и)?\s*)+)(?:лет|года|год)\b", text)
        ages = [int(age) for age in re.findall(r"\d{1,2}", listed.group(1))] if listed else []
        count = int(children.group(1)) if children else {"дв": 2, "тр": 3}.get(_few_kids(text), 1)
        if not ages:
            ages = [DEFAULT_CHILD_AGE] * count
            assumptions.append(f"Возраст ребёнка не указан — принят {DEFAULT_CHILD_AGE} лет.")
        found["children_ages"] = ages
    if re.search(
        r"(?:я|еду|поеду|лечу|летим)\s+(?:один|одна|сам|сама)\b|\bодин\s+(?:еду|поеду)", text
    ):
        found["adults"] = 1
    elif re.search(r"втроем", text):
        found["adults"] = 3
    elif re.search(r"вдвоем|с женой|с мужем|с девушкой|с парнем|с супруг", text):
        found["adults"] = 2
    if re.search(r"собак|пес\b|песик|щенк", text):
        found["pets"] = ["dog"]
    elif re.search(r"кошк|\bкот(?:ом|а|у|ик\w*)?\b|котен", text):
        found["pets"] = ["cat"]
    return found


def _few_kids(text: str) -> str:
    match = re.search(r"(дв|тр)(?:ое|умя|ух|емя|их)\s+(?:дет|ребят)", text)
    return match.group(1) if match else ""


def _budget(text: str) -> dict[str, Any]:
    found: dict[str, Any] = {}
    if re.search(r"недорог|бюджетн|экономн|подешевл|эконом\b", text):
        found["budget_style"] = "economy"
    elif re.search(r"премиум|люкс|подороже", text):
        found["budget_style"] = "premium"
    amount = re.search(r"(\d+)\s*(?:тыс\w*|к\b)", text) or re.search(
        r"(\d{1,3}(?:[ \N{NO-BREAK SPACE}]\d{3})+|\d{5,7})", text
    )
    if amount and re.search(r"бюджет|до\s+\d|не больше|не более|₽|руб", text):
        digits = int(re.sub(r"\D", "", amount.group(1)))
        found["budget_total_rub"] = digits * 1000 if digits < 1000 else digits
    return found


def _preferences(text: str) -> dict[str, Any]:
    found: dict[str, Any] = {}
    tags: list[str] = []
    if re.search(r"мор[еяю]\b|морск|пляж|купаться", text):
        tags.append("beach")
    if "тепл" in text and "beach" in tags:
        found.update(min_sea_temp_c=22, min_air_temp_c=22)
    if re.search(r"лыж|сноуборд", text):
        tags += ["ski", "mountains"]
    elif re.search(r"\bгор(?:ы|у|ах|ам)\b", text):
        tags.append("mountains")
    if re.search(r"экскурс|музе|достопримечат|культур", text):
        tags += ["city", "culture"]
    tags += [
        tag
        for pattern, tag in (
            (r"романт", "romantic"),
            (r"тих|спокойн", "quiet"),
            (r"шопинг", "shopping"),
            (r"бассейн", "pool"),
            (r"детск\w+ клуб|анимаци", "kids_club"),
            (r"\bспа\b|spa", "spa"),
        )
        if re.search(pattern, text)
    ]
    if tags:
        found["tags"] = list(dict.fromkeys(tags))
    if re.search(r"без\s+долг\w+\s+перел|недолг\w+\s+лет|короток\w+\s+перел|недалек", text):
        found["max_travel_hours"] = 5
    elif hours := re.search(r"до\s+(\d+)\s*(?:ч\b|час)", text):
        found["max_travel_hours"] = int(hours.group(1))
    if re.search(r"\bпоезд(?:ом|е|а|у|ы)?\b", text):
        found["transport_kinds"] = ["train"]
    if re.search(r"без\s+пересад|прям\w+\s+(?:рейс|перел)|нон-?стоп", text):
        found["max_stops"] = 0
    if re.search(r"бесплатн\w+\s+отмен|с\s+отмен", text):
        found["free_cancellation"] = True
    if re.search(r"все включено|all inclusive", text):
        found["meal_plan"] = "AI"
    if stars := re.search(r"(\d)\s*(?:звезд|\*)|пятизвезд", text):
        found["min_stars"] = int(stars.group(1)) if stars.group(1) else 5
    return found


def _changes(text: str) -> dict[str, Any]:
    found: dict[str, Any] = {}
    if days := _shift_days(text):
        found["shift_days"] = days
    if re.search(r"дешевл|бюджет\s+меньше|меньше\s+бюджет|сэкономит|уменьш\w+\s+бюджет", text):
        percent = re.search(r"(\d{1,2})\s*%", text)
        found["cheaper_by_percent"] = int(percent.group(1)) if percent else 10
    return found


def _shift_days(text: str) -> int | None:
    for pattern in SHIFT_PATTERNS:
        if match := re.search(pattern, text):
            number = int(match["n"]) if match["n"].isdigit() else NUMBER_WORDS[match["n"]]
            if (match["unit"] or "").startswith("недел") or match["n"] == "неделю":
                number *= 7
            return number if match["way"] == "позже" else -number
    return None


def wants_cart(text: str) -> bool:
    return bool(re.search(r"корзин|оформ|бронир|забронир|куп(?:ить|им|лю)", normalize(text)))


CONFIRMS_PAYMENT = re.compile(
    r"\b(?:оплачива\w+|оплатим|оплатите|оплатить|подтверждаю|подтверждаем|плачу|платим)\b"
)
DOUBTS_PAYMENT = re.compile(r"\bне\b|\bнет\b|\?|подума|позже|потом|\bесли\b|\bкак\b|способ")


def wants_payment(text: str) -> bool:
    """Явное подтверждение оплаты. Отказ, сомнение или вопрос про оплату — не подтверждение."""
    text = normalize(text)
    return bool(CONFIRMS_PAYMENT.search(text)) and not DOUBTS_PAYMENT.search(text)
