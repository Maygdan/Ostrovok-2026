"""Частичная пересборка плана: что устарело, что оставить, как уложиться в бюджет.

План пересобирается не с нуля: изменение условий затрагивает только часть слотов, а в
затронутых слотах остаётся прежний выбор, если он по-прежнему подходит.
"""

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass

from odin.domain.dates import DateWindow
from odin.domain.plan import (
    MAIN_SLOTS,
    ChangeKind,
    Offer,
    PlanDiff,
    Slot,
    SlotChange,
    TripPlan,
)
from odin.domain.ranking import Ranked
from odin.domain.request import TripRequest

_TRANSPORT = frozenset({Slot.OUTBOUND, Slot.INBOUND})
_PRICED = frozenset(MAIN_SLOTS)

# Какие слоты затрагивает изменение поля запроса. Даты и направление разбираются отдельно:
# даты сравниваются по итоговому окну, а смена направления пересобирает всё.
FIELD_SLOTS: dict[str, frozenset[Slot]] = {
    "origin": _TRANSPORT,
    "party": frozenset(Slot),
    "budget_total_rub": _PRICED,
    "budget_style": _PRICED,
    "max_travel_hours": _TRANSPORT,
    "transport_kinds": _TRANSPORT,
    "max_stops": _TRANSPORT,
    "min_stars": frozenset({Slot.HOTEL}),
    "meal_plan": frozenset({Slot.HOTEL}),
    "free_cancellation": frozenset({Slot.HOTEL}),
    "tags": frozenset({Slot.HOTEL}),
}

# Трансфер зависит от времени рейса и расположения отеля.
DEPENDENTS: dict[Slot, frozenset[Slot]] = {
    Slot.OUTBOUND: frozenset({Slot.TRANSFER_IN}),
    Slot.HOTEL: frozenset({Slot.TRANSFER_IN, Slot.TRANSFER_OUT}),
    Slot.INBOUND: frozenset({Slot.TRANSFER_OUT}),
}

# На сколько балл прежнего варианта может уступать лучшему, чтобы остаться в плане:
# пересборка не должна менять отель или рейс из-за пустяковой разницы в баллах.
STICKY_TOLERANCE = 0.08


def changed_fields(old: TripRequest, new: TripRequest) -> set[str]:
    old_values, new_values = old.model_dump(), new.model_dump()
    return {name for name, value in old_values.items() if value != new_values[name]}


def stale_slots(previous: TripPlan | None, request: TripRequest, window: DateWindow) -> set[Slot]:
    """Какие части плана нужно искать заново под новый запрос."""
    if previous is None or previous.destination.id != request.destination:
        return set(Slot)
    stale = {slot for slot in Slot if previous.get(slot) is None}
    if (previous.check_in, previous.check_out) != (window.check_in, window.check_out):
        stale |= _PRICED
    for name in changed_fields(previous.built_for, request):
        stale |= FIELD_SLOTS.get(name, frozenset())
    return with_dependents(stale)


def with_dependents(slots: Iterable[Slot]) -> set[Slot]:
    """Слоты и всё, что от них зависит (трансфер зависит от рейса и отеля)."""
    result = set(slots)
    for slot in tuple(result):
        result |= DEPENDENTS.get(slot, frozenset())
    return result


def choose[T: Offer](
    ranked: Sequence[Ranked[T]], incumbent_id: str | None = None, *, pinned: bool = False
) -> Ranked[T]:
    """Лучший вариант; прежний выбор сохраняется, если он почти так же хорош.

    Выбор пользователя (pinned) сохраняется, пока вариант вообще доступен.
    """
    best = ranked[0]
    if incumbent_id is None:
        return best
    for candidate in ranked:
        if candidate.option.id == incumbent_id:
            close_enough = best.score - candidate.score <= STICKY_TOLERANCE
            return candidate if pinned or close_enough else best
    return best


@dataclass(frozen=True)
class _Swap:
    slot: Slot
    replacement: Ranked[Offer]
    saving_rub: int
    quality_loss: float


def fit_to_budget(
    candidates: Mapping[Slot, Sequence[Ranked[Offer]]],
    picks: Mapping[Slot, Ranked[Offer]],
    budget_rub: int,
    *,
    other_costs_rub: int = 0,
    frozen: Collection[Slot] = (),
) -> dict[Slot, Ranked[Offer]]:
    """Заменяет выбранное на более дешёвое, пока итог не уложится в бюджет.

    Если хватает одной замены, берётся та, что теряет меньше всего качества. Если нет —
    самая выгодная по «экономия на единицу потерянного качества», и так до цели.
    `other_costs_rub` — траты вне picks, `frozen` — слоты, которые трогать нельзя.
    """
    current = dict(picks)
    while (overshoot := _total(current) + other_costs_rub - budget_rub) > 0:
        swap = _best_swap(candidates, current, overshoot, frozen)
        if swap is None:
            break
        current[swap.slot] = swap.replacement
    return current


def _total(picks: Mapping[Slot, Ranked[Offer]]) -> int:
    return sum(pick.option.total_price_rub for pick in picks.values())


def _best_swap(
    candidates: Mapping[Slot, Sequence[Ranked[Offer]]],
    picks: Mapping[Slot, Ranked[Offer]],
    overshoot_rub: int,
    frozen: Collection[Slot],
) -> _Swap | None:
    swaps = []
    for slot, pick in picks.items():
        if slot in frozen:
            continue
        for alternative in candidates.get(slot, ()):
            saving = pick.option.total_price_rub - alternative.option.total_price_rub
            if saving > 0:
                loss = max(pick.score - alternative.score, 0.0)
                swaps.append(_Swap(slot, alternative, saving, loss))
    if not swaps:
        return None
    sufficient = [swap for swap in swaps if swap.saving_rub >= overshoot_rub]
    if sufficient:
        return min(sufficient, key=lambda swap: (swap.quality_loss, -swap.saving_rub))
    return max(swaps, key=lambda swap: swap.saving_rub / (swap.quality_loss + 0.01))


def diff_plans(before: TripPlan | None, after: TripPlan) -> PlanDiff:
    """Что изменилось в каждой части плана и как сдвинулась итоговая цена.

    При смене направления тот же id (например, тип трансфера) — уже не то же предложение.
    """
    same_place = before is not None and before.destination.id == after.destination.id
    changes = [
        change
        for slot in Slot
        if (
            change := _slot_change(
                slot, before.get(slot) if before else None, after.get(slot), same_place=same_place
            )
        )
    ]
    return PlanDiff(
        changes=changes,
        price_delta_rub=after.total_price_rub - (before.total_price_rub if before else 0),
    )


def _slot_change(
    slot: Slot, old: Offer | None, new: Offer | None, *, same_place: bool
) -> SlotChange | None:
    if new is None:
        if old is None:
            return None
        return SlotChange(
            slot=slot,
            kind=ChangeKind.REMOVED,
            before=old.title,
            price_delta_rub=-old.total_price_rub,
        )
    if old is None:
        return SlotChange(
            slot=slot, kind=ChangeKind.ADDED, after=new.title, price_delta_rub=new.total_price_rub
        )
    if old == new:
        kind = ChangeKind.KEPT
    else:
        kind = ChangeKind.UPDATED if same_place and old.id == new.id else ChangeKind.REPLACED
    return SlotChange(
        slot=slot,
        kind=kind,
        before=old.title,
        after=new.title,
        price_delta_rub=new.total_price_rub - old.total_price_rub,
    )
