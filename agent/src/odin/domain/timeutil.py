"""Мелкие помощники для интервалов времени."""

from datetime import timedelta


def to_minutes(delta: timedelta) -> int:
    return round(delta.total_seconds() / 60)
