"""Общие части критериев: вес цены и оценка по цене."""

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from odin.domain.formatting import rub
from odin.domain.ranking import Verdict
from odin.domain.request import BudgetStyle

# Вес цены среди остальных критериев (их суммарный вес у отеля около 11): для «недорого» цена
# должна быть сопоставима со всем остальным вместе.
PRICE_WEIGHT = {BudgetStyle.ECONOMY: 6.0, BudgetStyle.STANDARD: 3.0, BudgetStyle.PREMIUM: 1.0}
# Крутизна оценки: для «недорого» переплата штрафуется сильнее, для «лишь бы удобно» — мягче.
PRICE_STEEPNESS = {BudgetStyle.ECONOMY: 2.0, BudgetStyle.STANDARD: 1.0, BudgetStyle.PREMIUM: 0.5}


@dataclass(frozen=True)
class PriceScale:
    """Ориентиры цены среди найденных вариантов."""

    cheapest: int
    typical: float  # медиана: устойчива к выбросам вроде самого дешёвого «без ничего»

    @classmethod
    def of(cls, prices: Sequence[int]) -> "PriceScale":
        return cls(min(prices), statistics.median(prices))


def price_verdict(
    price: int,
    scale: PriceScale,
    best_note: str,
    style: BudgetStyle,
    *,
    floor: int = 0,
) -> Verdict:
    """Оценка по цене: 0.5 у типичной, выше у дешёвых, ниже у дорогих; крутизна зависит от стиля.

    `floor` — сумма, меньше которой разница не стоит внимания: так 300 ₽ против 1 500 ₽ за
    трансфер не перевешивают удобство.
    """
    relative = (price + floor) / (scale.typical + floor)
    score = 1 / (1 + relative ** PRICE_STEEPNESS[style])
    extra = price - scale.cheapest
    if extra == 0:
        return Verdict(score, pro=best_note)
    notable = extra * 10 >= scale.cheapest + floor
    con = f"дороже самого дешёвого варианта на {rub(extra)}" if notable else None
    return Verdict(score, con=con)
