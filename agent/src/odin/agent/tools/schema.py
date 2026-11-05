"""JSON Schema параметров инструмента в самом совместимом с провайдерами виде."""

from typing import Any

from pydantic import BaseModel

DROPPED_KEYWORDS = frozenset({"title", "additionalProperties", "format"})
EXCLUSIVE_BOUNDS = {"exclusiveMinimum": ("minimum", 1), "exclusiveMaximum": ("maximum", -1)}


def tool_parameters(model: type[BaseModel]) -> dict[str, Any]:
    """Схема модели аргументов без `$ref`, `$defs`, `anyOf` с null, `title`, `format` и т. п.

    Не все OpenAI-совместимые серверы (Gemini, vLLM с управляемой генерацией) понимают ссылки,
    nullable-объединения, `additionalProperties`, `format` и «исключающие» границы, а плоская
    схема работает везде. Строгие проверки при этом остаются за pydantic: лишние поля, диапазоны
    и формат даты проверяются при разборе аргументов, а ошибка возвращается модели.
    """
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})
    return _simplify(schema, definitions)


def _simplify(node: Any, definitions: dict[str, Any]) -> Any:
    if isinstance(node, list):
        return [_simplify(item, definitions) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        target = definitions[node["$ref"].rsplit("/", 1)[-1]]
        return _simplify({**target, **{k: v for k, v in node.items() if k != "$ref"}}, definitions)
    if "anyOf" in node:
        variants = [variant for variant in node["anyOf"] if variant != {"type": "null"}]
        if len(variants) == 1:
            rest = {k: v for k, v in node.items() if k != "anyOf"}
            return _simplify({**rest, **variants[0]}, definitions)
    simplified: dict[str, Any] = {}
    for key, value in node.items():
        if key in DROPPED_KEYWORDS or (key == "default" and value is None):
            continue
        if key in EXCLUSIVE_BOUNDS:
            if node.get("type") == "integer":
                bound, step = EXCLUSIVE_BOUNDS[key]
                simplified[bound] = value + step
            continue
        if key == "properties":  # здесь ключи — имена полей, а не ключевые слова схемы
            simplified[key] = {name: _simplify(sub, definitions) for name, sub in value.items()}
        else:
            simplified[key] = _simplify(value, definitions)
    return simplified
