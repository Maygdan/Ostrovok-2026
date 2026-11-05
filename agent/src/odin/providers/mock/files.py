"""Чтение JSON-данных мок-провайдеров."""

import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent / "data"


def read_json(name: str) -> Any:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))
