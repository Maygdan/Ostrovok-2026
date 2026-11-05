"""Трансферы: жёсткие фильтры и критерии сравнения."""

from collections.abc import Sequence

from odin.domain.formatting import duration
from odin.domain.party import Party
from odin.domain.ranking import Criterion, Rule, Screened, Verdict, reject_when, screen
from odin.domain.request import BudgetStyle, TripRequest
from odin.domain.scoring.common import PRICE_WEIGHT, PriceScale, price_verdict
from odin.domain.transfer import TransferKind, TransferOffer

PRICE_FLOOR_RUB = 3_000  # на фоне стоимости поездки разница в пару тысяч за трансфер невелика
COMFORT = {
    TransferKind.PRIVATE: 1.0,
    TransferKind.TAXI: 0.85,
    TransferKind.SHUTTLE: 0.5,
    TransferKind.PUBLIC: 0.2,
}


def screen_transfers(
    offers: Sequence[TransferOffer], request: TripRequest
) -> Screened[TransferOffer]:
    rules: list[Rule[TransferOffer]] = []
    if request.party.has_pets:
        rules.append(reject_when("не перевозит животных", lambda o: not o.pets_allowed))
    return screen(offers, rules)


def transfer_criteria(
    request: TripRequest, offers: Sequence[TransferOffer]
) -> list[Criterion[TransferOffer]]:
    scale = PriceScale.of([offer.total_price_rub for offer in offers])
    quickest = min(offer.duration_minutes for offer in offers)
    criteria = [
        Criterion(
            "price",
            PRICE_WEIGHT[request.budget_style],
            lambda o: _price(o, scale, request.budget_style),
        ),
        Criterion("duration", 1.5, lambda o: _duration(o, quickest)),
        Criterion("comfort", 1.5, lambda o: _comfort(o, request.party)),
        Criterion("meeting", 0.5, _meeting),
    ]
    if request.party.needs_child_seat:
        criteria.append(Criterion("child_seat", 2.5, _child_seat))
    return criteria


def _price(offer: TransferOffer, scale: PriceScale, style: BudgetStyle) -> Verdict:
    return price_verdict(
        offer.total_price_rub, scale, "самый дешёвый трансфер", style, floor=PRICE_FLOOR_RUB
    )


def _duration(offer: TransferOffer, quickest: int) -> Verdict:
    score = quickest / offer.duration_minutes
    if offer.duration_minutes - quickest >= 20:
        return Verdict(score, con=f"дорога {duration(offer.duration_minutes)} — заметно дольше")
    return Verdict(score)


def _comfort(offer: TransferOffer, party: Party) -> Verdict:
    score = COMFORT[offer.kind]
    if offer.kind in (TransferKind.PRIVATE, TransferKind.TAXI):
        return Verdict(score, pro="отдельная машина: без ожидания других пассажиров")
    if offer.kind is TransferKind.SHUTTLE:
        return Verdict(score, con="групповой трансфер: остановки по пути и ожидание пассажиров")
    with_whom = "с багажом и детьми" if party.has_children else "с багажом"
    return Verdict(score, con=f"общественный транспорт: {with_whom} неудобно")


def _meeting(offer: TransferOffer) -> Verdict:
    if offer.meet_and_greet:
        return Verdict(1.0, pro="встреча с табличкой в зале прилёта")
    return Verdict(0.5)


def _child_seat(offer: TransferOffer) -> Verdict:
    if offer.child_seat:
        return Verdict(1.0, pro="детское кресло в машине")
    return Verdict(
        0.1,
        con="нет детского кресла",
        risk="маленького ребёнка придётся возить без кресла — это небезопасно",
    )
