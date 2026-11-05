"""Тексты ответов заглушки: собираются из результатов инструментов, как это сделала бы модель."""

from datetime import datetime
from typing import Any

from odin.agent.llm.stub.dialogue import Dialogue, ToolResult
from odin.domain.formatting import (
    MONTHS_GENITIVE,
    MONTHS_PREPOSITIONAL,
    date_range,
    nights,
    rub,
    signed_rub,
    temperature,
)

HELP = (
    "Это демо-режим без подключённой модели: я понимаю типовые формулировки и показываю, как "
    "работает весь путь — от запроса до имитации оплаты.\n\n"
    "Попробуйте, например:\n"
    "• «Хочу к тёплому морю в сентябре, недорого, с ребёнком, без долгих перелётов»\n"
    "• «Давай первый вариант» — выбрать направление из списка\n"
    "• «А можно на два дня позже?», «Бюджет меньше», «С нами будет собака» — пересборка плана\n"
    "• «Оформляй» — корзина, затем «Оплачиваю»\n\n"
    "Чтобы я понимал любые формулировки, задайте LLM_API_KEY в .env."
)
NOT_UNDERSTOOD = (
    "В демо-режиме я не разобрал это сообщение. Назовите месяц поездки и пожелания "
    "(море, горы, город, бюджет, с кем едете) или выберите направление из списка. "
    "Подсказки — в справке: напишите «помощь»."
)
ALREADY_ORDERED = (
    "Заказ уже оформлен (имитация). Изменения после покупки в демо пока не поддерживаются — "
    "для новой поездки начните новый диалог."
)
PART_ORDER = ("outbound", "transfer_in", "hotel", "transfer_out", "inbound")
PART_NAMES = {
    "outbound": "Дорога туда",
    "transfer_in": "Трансфер в отель",
    "hotel": "Отель",
    "transfer_out": "Трансфер из отеля",
    "inbound": "Дорога обратно",
}
CHANGE_WORDS = {
    "kept": "без изменений",
    "updated": "тот же вариант на новые даты",
    "replaced": "заменён",
    "added": "добавлен",
    "removed": "убран",
}
SEVERITY_WORDS = {"error": "Блокирует оформление", "warning": "Внимание", "info": "К сведению"}


def compose(dialogue: Dialogue) -> str:
    """Ответ по результатам инструментов, выполненных в этом ходу."""
    failed = next((result for result in dialogue.turn if not result.ok), None)
    if failed is not None:
        return _error(failed)
    if paid := dialogue.this_turn("pay_cart"):
        return _order(paid.data)
    if cart := dialogue.this_turn("create_cart"):
        return _cart(cart.data)
    plan = dialogue.this_turn("build_plan") or dialogue.this_turn("select_option")
    if plan:
        return _plan(plan.data)
    options = dialogue.this_turn("search_destinations")
    if options:
        update = dialogue.this_turn("update_trip_request")
        request = update.data["request"] if update else {}
        return _destinations(request, options.data)
    return NOT_UNDERSTOOD


def _error(result: ToolResult) -> str:
    text = f"Не получилось: {result.data['error']}"
    if result.data.get("ask_user"):
        text += "\nУточните, пожалуйста, этот момент — и я продолжу."
    return text


def _destinations(request: dict[str, Any], result: dict[str, Any]) -> str:
    lines = [f"Понял запрос: {_describe(request)}."]
    if assumptions := request.get("assumptions"):
        lines += ["Допущения (скажите, если не так):", *(f"• {item}" for item in assumptions)]
    options = result["options"]
    if not options:
        lines += ["", "Под эти условия ничего не подошло.", _excluded(result["excluded"])]
        lines.append("Могу смягчить условия: бюджет, время в пути или даты. Что поменять?")
        return "\n".join(lines)
    lines += ["", f"Подходящие направления на {_dates(result)}:"]
    for number, option in enumerate(options, 1):
        lines += _destination(number, option)
    if result["excluded"]:
        lines += ["", _excluded(result["excluded"])]
    lines += ["", "Какое направление берём в проработку? Назовите его или номер."]
    return "\n".join(lines)


def _destination(number: int, option: dict[str, Any]) -> list[str]:
    lines = [
        f"{number}. {option['name']} ({option['country']}) — от {rub(option['price_from_rub'])} "
        f"на всех, в пути {option['travel_time']}",
        f"   Погода: {option['weather']}",
    ]
    lines += _notes(option, indent="   ")
    return lines


def _excluded(excluded: list[dict[str, Any]]) -> str:
    if not excluded:
        return ""
    return "Не подошли: " + "; ".join(f"{e['name']} — {e['reason']}" for e in excluded) + "."


def _plan(result: dict[str, Any]) -> str:
    plan = result["plan"]
    party = plan["party"]
    verb = "Пересобрал" if "changes" in result else "Собрал"
    lines = [
        f"{verb} поездку: {plan['destination']['name']}, {_dates(plan)} "
        f"({nights(plan['nights'])}), {party}.",
        f"Итого: {rub(plan['total_price_rub'])}.",
    ]
    if weather := plan.get("weather"):
        lines.append(f"Погода в эти даты: {weather}.")
    if "changes" in result:
        lines += ["", *_changes(result["changes"])]
    for note in result.get("notes", []):
        lines.append(f"Важно: {note}")
    for part in PART_ORDER:
        if part in plan:
            lines += ["", *_part(PART_NAMES[part], plan[part])]
    lines += ["", *_issues(plan.get("issues", []))]
    lines += ["", _next_step(result)]
    return "\n".join(lines)


def _part(label: str, part: dict[str, Any]) -> list[str]:
    title = part.get("name") or part["title"]
    lines = [f"{label}: {title} — {rub(part['total_price_rub'])}"]
    if "departs" in part:
        lines.append(
            f"   {_when(part['departs'])} → {_when(part['arrives'])}, в пути {part['travel_time']}"
        )
    elif "pickup" in part:
        lines.append(f"   Подача {_when(part['pickup'])}, в пути {part['travel_time']}")
    else:
        lines.append(f"   {part['room']}, {part['meal']}; {_cancellation(part)}")
    return lines + _notes(part, indent="   ")


def _cancellation(hotel: dict[str, Any]) -> str:
    if until := hotel.get("free_cancellation_until"):
        return f"бесплатная отмена до {_day(until)}"
    return "невозвратный тариф"


def _notes(item: dict[str, Any], indent: str) -> list[str]:
    labels = (("pros", "Почему подходит"), ("cons", "Чем пожертвовали"), ("risks", "Риски"))
    return [f"{indent}{label}: {'; '.join(item[key])}" for key, label in labels if item.get(key)]


def _changes(changes: dict[str, Any]) -> list[str]:
    lines = ["Что изменилось:"]
    for change in changes["parts"]:
        word = CHANGE_WORDS[change["status"]]
        detail = word
        if change["status"] == "replaced":
            detail = f"{word}: было «{change.get('was', '—')}», стало «{change.get('now', '—')}»"
        if delta := change.get("price_change_rub"):
            detail += f", цена {signed_rub(delta)}"
        lines.append(f"• {PART_NAMES[change['part']]}: {detail}")
    total = changes["total_price_change_rub"]
    lines.append(
        f"Итоговая цена изменилась на {signed_rub(total)}." if total else "Цена не изменилась."
    )
    return lines


def _issues(issues: list[dict[str, Any]]) -> list[str]:
    visible = [issue for issue in issues if issue["severity"] != "info"]
    if not visible:
        return ["Стыковки проверены: прилёт, заселение, трансферы и вылет согласованы."]
    lines = ["Проверка стыковок:"]
    lines += [f"• {SEVERITY_WORDS[i['severity']]}: {i['message']}" for i in visible]
    return lines


def _next_step(result: dict[str, Any]) -> str:
    if result["ready_for_cart"]:
        return "Оформить в корзину? Или поменять даты, бюджет, отель, состав группы."
    return "Оформить пока нельзя: есть блокирующие проблемы. Измените даты, рейс или бюджет."


def _cart(result: dict[str, Any]) -> str:
    cart = result["cart"]
    lines = ["Корзина собрана:"]
    for item in cart["items"]:
        conditions = f" ({item['conditions']})" if item.get("conditions") else ""
        lines.append(
            f"• {PART_NAMES[item['part']]}: {item['title']} — {rub(item['price_rub'])}{conditions}"
        )
    lines += [
        f"Итого: {rub(cart['total_price_rub'])}.",
        "",
        "Оплата — имитация, деньги не списываются. Подтверждаете оплату? Напишите «оплачиваю».",
    ]
    return "\n".join(lines)


def _order(result: dict[str, Any]) -> str:
    order = result["order"]
    lines = [f"Готово! Заказ {order['id']} оплачен на {rub(order['total_price_rub'])} (имитация)."]
    for booking in order["bookings"]:
        lines.append(
            f"• {PART_NAMES[booking['part']]}: код подтверждения {booking['confirmation_code']}"
        )
    lines.append("Хорошей поездки!")
    return "\n".join(lines)


def _describe(request: dict[str, Any]) -> str:
    parts = []
    if date_from := request.get("date_from"):
        parts.append(f"вылет {_day(date_from)}")
    elif month := request.get("month"):
        parts.append(f"в {MONTHS_PREPOSITIONAL[month - 1]}")
    if request.get("nights"):
        parts.append(nights(request["nights"]))
    parts.append(request.get("party_label", ""))
    if budget := request.get("budget_total_rub"):
        parts.append(f"бюджет до {rub(budget)}")
    elif request.get("budget_style") == "economy":
        parts.append("недорого")
    if request.get("max_travel_hours"):
        parts.append(f"дорога до {request['max_travel_hours']:g} ч")
    if request.get("min_sea_temp_c") is not None:
        parts.append(f"вода от {temperature(request['min_sea_temp_c'])}")
    if request.get("max_stops") == 0:
        parts.append("без пересадок")
    if request.get("free_cancellation"):
        parts.append("с бесплатной отменой отеля")
    return ", ".join(part for part in parts if part)


def _dates(result: dict[str, Any]) -> str:
    return date_range(
        datetime.fromisoformat(result["check_in"]).date(),
        datetime.fromisoformat(result["check_out"]).date(),
    )


def _day(iso: str) -> str:
    moment = datetime.fromisoformat(iso)
    return f"{moment.day} {MONTHS_GENITIVE[moment.month - 1]}"


def _when(local: str) -> str:
    """'2026-11-10 11:15' -> '10 ноября, 11:15'."""
    moment = datetime.strptime(local, "%Y-%m-%d %H:%M")
    return f"{moment.day} {MONTHS_GENITIVE[moment.month - 1]}, {moment:%H:%M}"
