"""Инструменты агента. Чтобы добавить новый, опишите его в модуле и включите сюда."""

from odin.agent.tools import checkout, plan, request, search
from odin.agent.tools.base import Tool


def default_tools() -> list[Tool]:
    return [*request.TOOLS, *search.TOOLS, *plan.TOOLS, *checkout.TOOLS]
