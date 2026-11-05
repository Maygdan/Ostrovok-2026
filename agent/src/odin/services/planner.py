"""Сборка и частичная пересборка плана поездки."""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import cast

from odin.domain.errors import DomainError
from odin.domain.hotel import HotelOffer
from odin.domain.junctions import check_plan
from odin.domain.plan import (
    MAIN_SLOTS,
    SLOT_LABELS,
    TRANSFER_SLOTS,
    Explanation,
    IssueCode,
    Offer,
    PlanDiff,
    Slot,
    TripPlan,
)
from odin.domain.ranking import Ranked
from odin.domain.rebuild import choose, diff_plans, fit_to_budget, stale_slots, with_dependents
from odin.domain.request import TripRequest
from odin.domain.transfer import TransferOffer
from odin.domain.transport import TransportOffer
from odin.providers.interfaces import Providers
from odin.services.search import Search, Trip, TripSearch

# Пока трансферы не подобраны, на них откладывается эта доля бюджета.
TRANSFER_RESERVE = 0.05


@dataclass(frozen=True)
class BuildResult:
    plan: TripPlan
    diff: PlanDiff
    recomputed: frozenset[Slot]
    notes: list[str] = field(default_factory=list)


class TripPlanner:
    def __init__(self, providers: Providers) -> None:
        self.search = TripSearch(providers)
        self._providers = providers

    async def build(
        self,
        request: TripRequest,
        previous: TripPlan | None,
        today: date,
        forced: Mapping[Slot, str] | None = None,
    ) -> BuildResult:
        """Собирает план или пересобирает только затронутые изменениями части.

        `forced` — выбор пользователя: часть плана и id нужного предложения. Такая часть
        закрепляется и не меняется при последующих пересборках, пока предложение доступно.
        """
        trip = await self.search.resolve_trip(request, today)
        base = previous if previous and previous.destination.id == trip.destination.id else None
        forced = dict(forced or {})
        stale = with_dependents(forced) | stale_slots(base, request, trip.window)
        if base is not None and not stale:
            return BuildResult(base, diff_plans(base, base), frozenset(), ["План уже актуален."])
        weather = await self._providers.weather.month_weather(
            trip.destination, trip.window.check_in.month
        )
        revision = previous.revision + 1 if previous else 1
        plan, notes = await _Rebuild(self.search, trip, base, stale, forced, revision).execute()
        if (spare := _unpinned_kept(base, stale, forced)) and _over_budget(plan):
            stale = with_dependents(stale | spare)
            plan, notes = await _Rebuild(self.search, trip, base, stale, forced, revision).execute()
            notes.append(
                "С прежними частями плана новый выбор не укладывался в бюджет, "
                "поэтому пересмотрены и они."
            )
        plan = plan.model_copy(update={"weather": weather})
        if previous is not None and _same_trip(plan, previous):
            plan = plan.model_copy(update={"revision": previous.revision})
        return BuildResult(plan, diff_plans(previous, plan), frozenset(stale), notes)


def _unpinned_kept(
    base: TripPlan | None, stale: set[Slot], forced: Mapping[Slot, str]
) -> set[Slot]:
    """Основные части, которые не пересматривались и не закреплены пользователем."""
    pinned = set(base.pinned if base else ()) | set(forced)
    return {slot for slot in MAIN_SLOTS if slot not in stale and slot not in pinned}


def _over_budget(plan: TripPlan) -> bool:
    return any(issue.code is IssueCode.OVER_BUDGET for issue in plan.issues)


def _same_trip(plan: TripPlan, previous: TripPlan) -> bool:
    """Те же предложения и те же проблемы: ревизия остаётся, корзина по-прежнему верна.

    Ревизия растёт при любой иной перемене, в том числе при смене направления или когда
    прежние предложения вдруг перестали укладываться в бюджет.
    """
    return plan.issues == previous.issues and all(
        plan.get(slot) == previous.get(slot) for slot in Slot
    )


class _Rebuild:
    """Один проход пересборки: что искать заново, что оставить, что закреплено пользователем."""

    def __init__(
        self,
        search: TripSearch,
        trip: Trip,
        base: TripPlan | None,
        stale: set[Slot],
        forced: Mapping[Slot, str],
        revision: int,
    ) -> None:
        self._search = search
        self._trip = trip
        self._base = base
        self._stale = stale
        self._forced = forced
        self._revision = revision
        self._pinned = (set(base.pinned) if base else set()) | set(forced)
        self._notes: list[str] = []
        self._searches: dict[Slot, Search] = {}
        self._picks: dict[Slot, Ranked[Offer]] = {}

    async def execute(self) -> tuple[TripPlan, list[str]]:
        await self._pick_main_slots()
        await self._pick_transfers()
        return self._assemble(), self._notes

    async def _pick_main_slots(self) -> None:
        slots = [slot for slot in MAIN_SLOTS if slot in self._stale]
        found = await asyncio.gather(*(self._find_main(slot) for slot in slots))
        for slot, search in zip(slots, found, strict=True):
            self._searches[slot] = search
            self._picks[slot] = self._pick(slot, search)
        self._fit_budget(
            slots, transfers_pending=any(slot in self._stale for slot in TRANSFER_SLOTS)
        )

    async def _find_main(self, slot: Slot) -> Search:
        if slot is Slot.HOTEL:
            return await self._search.hotels(self._trip)
        return await self._search.transport(self._trip, slot)

    async def _pick_transfers(self) -> None:
        slots = [slot for slot in TRANSFER_SLOTS if slot in self._stale]
        if not slots:
            return
        hotel = self._hotel()
        for slot in slots:
            transport = self._transport(Slot.OUTBOUND if slot is Slot.TRANSFER_IN else Slot.INBOUND)
            search = await self._search.transfers(self._trip, slot, transport, hotel)
            self._searches[slot] = search
            self._picks[slot] = self._pick(slot, search)
        self._fit_budget(slots, transfers_pending=False)

    def _hotel(self) -> HotelOffer:
        return cast(HotelOffer, self._offer(Slot.HOTEL))

    def _transport(self, slot: Slot) -> TransportOffer:
        return cast(TransportOffer, self._offer(slot))

    def _transfer(self, slot: Slot) -> TransferOffer:
        return cast(TransferOffer, self._offer(slot))

    def _offer(self, slot: Slot) -> Offer:
        """Актуальное предложение для части: только что выбранное или прежнее."""
        if slot in self._picks:
            return self._picks[slot].option
        offer = self._base.get(slot) if self._base else None
        if offer is None:
            raise DomainError(f"{SLOT_LABELS[slot]}: нечего подставить, часть плана не собрана.")
        return offer

    def _pick(self, slot: Slot, search: Search) -> Ranked[Offer]:
        label = SLOT_LABELS[slot]
        search.require_options(label.lower())
        if slot in self._forced:
            return self._forced_pick(slot, search)
        previous = self._base.get(slot) if self._base else None
        chosen = choose(
            search.ranked,
            previous.id if previous else None,
            pinned=slot in self._pinned,
        )
        if previous and slot in self._pinned and chosen.option.id != previous.id:
            self._pinned.discard(slot)
            reason = search.why_dropped(previous.id)
            problem = f"не подходит ({reason})" if reason else "недоступен"
            self._notes.append(
                f"{label}: выбранный вами вариант «{previous.title}» больше {problem}, "
                f"подобран «{chosen.option.title}»."
            )
        return chosen

    def _forced_pick(self, slot: Slot, search: Search) -> Ranked[Offer]:
        option_id = self._forced[slot]
        chosen = search.find(option_id)
        if chosen is not None:
            return chosen
        reason = search.why_dropped(option_id)
        if reason:
            raise DomainError(f"Вариант «{option_id}» не подходит: {reason}.")
        raise DomainError(f"Вариант «{option_id}» не найден среди доступных: {SLOT_LABELS[slot]}.")

    def _fit_budget(self, slots: list[Slot], *, transfers_pending: bool) -> None:
        """Подменяет выбранное на более дешёвое, если не укладываемся в бюджет."""
        budget = self._trip.request.budget_total_rub
        if budget is None or not slots:
            return
        kept = (self._base.get(slot) for slot in Slot if self._base and slot not in self._stale)
        fixed = sum(offer.total_price_rub for offer in kept if offer is not None)
        fixed += sum(
            pick.option.total_price_rub for slot, pick in self._picks.items() if slot not in slots
        )
        if transfers_pending:
            fixed += round(budget * TRANSFER_RESERVE)
        fitted = fit_to_budget(
            {slot: self._searches[slot].ranked for slot in slots},
            {slot: self._picks[slot] for slot in slots},
            budget,
            other_costs_rub=fixed,
            frozen=self._pinned,
        )
        self._picks.update(fitted)

    def _assemble(self) -> TripPlan:
        base, trip = self._base, self._trip
        explanations: dict[Slot, Explanation] = dict(base.explanations) if base else {}
        explanations.update({slot: pick.explanation() for slot, pick in self._picks.items()})
        plan = TripPlan(
            revision=self._revision,
            destination=trip.destination,
            check_in=trip.window.check_in,
            check_out=trip.window.check_out,
            explanations=explanations,
            pinned=[slot for slot in Slot if slot in self._pinned],
            built_for=trip.request.model_copy(deep=True),
            outbound=self._transport(Slot.OUTBOUND),
            hotel=self._hotel(),
            inbound=self._transport(Slot.INBOUND),
            transfer_in=self._transfer(Slot.TRANSFER_IN),
            transfer_out=self._transfer(Slot.TRANSFER_OUT),
        )
        return plan.model_copy(update={"issues": check_plan(plan)})
