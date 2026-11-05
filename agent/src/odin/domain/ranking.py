"""Сравнение вариантов: жёсткие фильтры и взвешенные критерии с объяснениями.

Критерий одновременно выставляет балл и формулирует, что в варианте хорошо, чем придётся
пожертвовать и чем рискуем. Поэтому объяснение выбора строится из тех же фактов, что и
сам выбор, и не расходится с ним.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from odin.domain.plan import Explanation


class Verdict(NamedTuple):
    """Оценка одного варианта по одному критерию: балл 0..1 и пояснения, если есть что сказать."""

    score: float
    pro: str | None = None
    con: str | None = None
    risk: str | None = None


@dataclass(frozen=True)
class Criterion[T]:
    name: str
    weight: float
    judge: Callable[[T], Verdict]


@dataclass(frozen=True)
class Ranked[T]:
    option: T
    score: float
    pros: tuple[str, ...] = ()
    cons: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()

    def explanation(self) -> Explanation:
        return Explanation(
            score=round(self.score, 2),
            pros=list(self.pros),
            cons=list(self.cons),
            risks=list(self.risks),
        )


def rank[T](options: Sequence[T], criteria: Sequence[Criterion[T]]) -> list[Ranked[T]]:
    """Лучшие варианты первыми. При равных баллах сохраняется порядок входного списка."""
    total_weight = sum(criterion.weight for criterion in criteria)
    ranked = []
    for option in options:
        verdicts = [criterion.judge(option) for criterion in criteria]
        weighted = sum(c.weight * v.score for c, v in zip(criteria, verdicts, strict=True))
        ranked.append(
            Ranked(
                option=option,
                score=weighted / total_weight,
                pros=tuple(v.pro for v in verdicts if v.pro),
                cons=tuple(v.con for v in verdicts if v.con),
                risks=tuple(v.risk for v in verdicts if v.risk),
            )
        )
    return sorted(ranked, key=lambda item: item.score, reverse=True)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


type Rule[T] = Callable[[T], str | None]
"""Жёсткое условие: возвращает причину отказа или None, если вариант подходит."""


@dataclass(frozen=True)
class Dropped[T]:
    option: T
    reason: str


@dataclass(frozen=True)
class Screened[T]:
    kept: list[T]
    dropped: list[Dropped[T]]

    @property
    def reasons(self) -> dict[str, int]:
        """Сколько вариантов отсеяно по каждой причине."""
        counts: dict[str, int] = {}
        for item in self.dropped:
            counts[item.reason] = counts.get(item.reason, 0) + 1
        return counts


def reject_when[T](reason: str, predicate: Callable[[T], bool]) -> Rule[T]:
    """Правило для screen(): отказать с указанной причиной, если predicate истинен."""
    return lambda option: reason if predicate(option) else None


def screen[T](options: Sequence[T], rules: Sequence[Rule[T]]) -> Screened[T]:
    """Отсеивает варианты, нарушающие жёсткие условия. Правило возвращает причину отказа."""
    kept: list[T] = []
    dropped: list[Dropped[T]] = []
    for option in options:
        reason = next((found for rule in rules if (found := rule(option))), None)
        if reason is None:
            kept.append(option)
        else:
            dropped.append(Dropped(option, reason))
    return Screened(kept, dropped)
