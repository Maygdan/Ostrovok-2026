"""Разбор истории диалога для заглушки: что уже сделано и что вернули инструменты."""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from odin.agent.llm.types import Message, Role

PLAN_TOOLS = ("build_plan", "select_option")
ORDINALS = {"перв": 0, "втор": 1, "трет": 2, "четв": 3}


@dataclass(frozen=True)
class ToolResult:
    name: str
    data: dict[str, Any]

    @property
    def ok(self) -> bool:
        return "error" not in self.data


class Dialogue:
    """Последнее сообщение пользователя, результаты инструментов этого хода и прошлых."""

    def __init__(self, messages: Sequence[Message]) -> None:
        names: dict[str, str] = {}
        self.user_text = ""
        last_user = -1
        results: list[tuple[int, ToolResult]] = []
        for index, message in enumerate(messages):
            if message.role is Role.USER:
                self.user_text, last_user = message.content, index
            elif message.role is Role.ASSISTANT:
                names.update({call.id: call.name for call in message.tool_calls})
            elif message.role is Role.TOOL:
                name = names.get(message.tool_call_id or "", "?")
                results.append((index, ToolResult(name, json.loads(message.content))))
        self._past = [result for index, result in results if index < last_user]
        self.turn = [result for index, result in results if index > last_user]

    def this_turn(self, name: str) -> ToolResult | None:
        return next((result for result in self.turn if result.name == name), None)

    @property
    def plan_built(self) -> bool:
        return any(r.ok and r.name in PLAN_TOOLS for r in self._past)

    @property
    def ordered(self) -> bool:
        return any(r.ok and r.name == "pay_cart" for r in self._past)

    @property
    def cart_open(self) -> bool:
        """Корзина создана после последней сборки плана и ещё не оплачена."""
        open_cart = False
        for result in self._past:
            if not result.ok:
                continue
            if result.name in PLAN_TOOLS or result.name == "pay_cart":
                open_cart = False
            elif result.name == "create_cart":
                open_cart = True
        return open_cart

    def offered_destinations(self) -> list[dict[str, Any]]:
        """Направления из последней выдачи search_destinations."""
        for result in reversed(self._past):
            if result.ok and result.name == "search_destinations":
                return result.data.get("options", [])
        return []

    def assumptions(self) -> list[str]:
        """Допущения из последнего состояния запроса, которое вернул update_trip_request."""
        for result in reversed(self._past):
            if result.ok and result.name == "update_trip_request":
                return list(result.data.get("request", {}).get("assumptions", []))
        return []

    def chosen_destination(self) -> str | None:
        """id направления, которое пользователь выбрал по номеру или названию из выдачи."""
        options = self.offered_destinations()
        text = self.user_text.lower().replace("ё", "е")
        for stem, index in ORDINALS.items():
            if re.search(rf"\b{stem}\w*", text) and index < len(options):
                return options[index]["id"]
        number = re.search(r"(?:вариант|номер|№|#)\s*(\d)\b", text) or re.fullmatch(
            r"\s*(\d)\s*", text
        )
        if number and 0 < int(number.group(1)) <= len(options):
            return options[int(number.group(1)) - 1]["id"]
        for option in options:
            name = option["name"].lower().replace("ё", "е")
            if name[: max(4, len(name) - 2)] in text:
                return option["id"]
        return None
