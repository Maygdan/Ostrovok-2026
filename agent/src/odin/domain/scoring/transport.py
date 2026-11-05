"""Перелёты и поезда: жёсткие фильтры и критерии сравнения."""

from collections.abc import Sequence
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from odin.domain.formatting import clock, day_month, duration, hours, plural, rub
from odin.domain.junctions import MIN_LAYOVER_MINUTES, arrives_for_check_in
from odin.domain.plan import Slot
from odin.domain.ranking import Criterion, Rule, Screened, Verdict, reject_when, screen
from odin.domain.request import BudgetStyle, TripRequest
from odin.domain.scoring.common import PRICE_WEIGHT, PriceScale, price_verdict
from odin.domain.transport import TransportOffer

CHILD_TIMING_WEIGHT = 3.5  # с детьми ночные и сверхранние рейсы особенно неудобны


def screen_transport(
    offers: Sequence[TransportOffer], request: TripRequest
) -> Screened[TransportOffer]:
    return screen(offers, _rules(request))


def screen_outbound(
    offers: Sequence[TransportOffer], request: TripRequest, check_in: date, tz: ZoneInfo
) -> Screened[TransportOffer]:
    """Дорога туда: общие правила и прибытие к заезду (`tz` — пояс направления).

    Предложения ищутся на день заезда и накануне; ночной поезд или дальний перелёт, вылетевший
    накануне, прибывает как раз вовремя, а тот же рейс в день заезда — уже на следующие сутки.
    """
    in_time: Rule[TransportOffer] = reject_when(
        "прибывает не к заезду",
        lambda o: not arrives_for_check_in(o.arrives_at.astimezone(tz), check_in),
    )
    return screen(offers, [*_rules(request), in_time])


def _rules(request: TripRequest) -> list[Rule[TransportOffer]]:
    rules: list[Rule[TransportOffer]] = [
        reject_when("вид транспорта не подходит", lambda o: o.kind not in request.transport_kinds)
    ]
    if request.max_travel_hours is not None:
        limit_minutes = round(request.max_travel_hours * 60)
        reason = f"в пути дольше {hours(request.max_travel_hours)}"
        rules.append(reject_when(reason, lambda o: o.duration_minutes > limit_minutes))
    if request.max_stops is not None:
        stops = request.max_stops
        reason = "есть пересадки" if stops == 0 else f"пересадок больше {stops}"
        rules.append(reject_when(reason, lambda o: o.stops > stops))
    if request.party.has_pets:
        rules.append(reject_when("не перевозит животных", lambda o: not o.pets_allowed))
    if request.budget_total_rub is not None:
        budget = request.budget_total_rub
        rules.append(reject_when("дороже всего бюджета", lambda o: o.total_price_rub > budget))
    return rules


def transport_criteria(
    request: TripRequest,
    offers: Sequence[TransportOffer],
    slot: Slot,
    destination_tz: ZoneInfo,
    day: date,
) -> list[Criterion[TransportOffer]]:
    """`day` — дата заезда для дороги туда и дата выезда для дороги обратно."""
    scale = PriceScale.of([offer.total_price_rub for offer in offers])
    quickest = min(offer.door_to_door_minutes for offer in offers)
    any_stops = any(offer.stops for offer in offers)
    if slot is Slot.OUTBOUND:

        def timing(offer: TransportOffer) -> Verdict:
            return _outbound_timing(offer, destination_tz, day)
    else:

        def timing(offer: TransportOffer) -> Verdict:
            return _inbound_timing(offer, destination_tz, day)

    timing_weight = CHILD_TIMING_WEIGHT if request.party.has_children else 2.0
    return [
        Criterion(
            "price",
            PRICE_WEIGHT[request.budget_style],
            lambda o: _price(o, scale, request.budget_style),
        ),
        Criterion("duration", 2.5, lambda o: _duration(o, quickest)),
        Criterion("stops", 1.5, lambda o: _stops(o, any_stops)),
        Criterion("timing", timing_weight, timing),
        Criterion("baggage", 1.0, _baggage),
        Criterion("fare", 0.7, _fare),
    ]


def _price(offer: TransportOffer, scale: PriceScale, style: BudgetStyle) -> Verdict:
    best = f"самый дешёвый вариант: {rub(offer.total_price_rub)} за всех"
    return price_verdict(offer.total_price_rub, scale, best, style)


def _duration(offer: TransportOffer, quickest: int) -> Verdict:
    """Сравниваем вместе с запасом на аэропорт или вокзал, иначе поезд всегда проигрывает."""
    extra = offer.door_to_door_minutes - quickest
    score = quickest / offer.door_to_door_minutes
    in_transit = duration(offer.duration_minutes)
    if extra == 0:
        return Verdict(score, pro=f"самый быстрый вариант: {in_transit} в пути")
    if extra >= 60:
        return Verdict(
            score, con=f"в пути {in_transit} — на {duration(extra)} дольше самого быстрого"
        )
    return Verdict(score)


def _stops(offer: TransportOffer, any_stops: bool) -> Verdict:
    if offer.stops == 0:
        return Verdict(1.0, pro="без пересадок" if any_stops else None)
    word = plural(offer.stops, "пересадка", "пересадки", "пересадок")
    layovers = ", ".join(duration(minutes) for minutes in offer.layovers_minutes)
    shortest = min(offer.layovers_minutes)
    risk = None
    if shortest < MIN_LAYOVER_MINUTES[offer.international]:
        risk = f"пересадка всего {duration(shortest)}: при задержке рейса можно не успеть"
    return Verdict(
        0.45 if offer.stops == 1 else 0.2,
        con=f"{offer.stops} {word} ({layovers})",
        risk=risk,
    )


def _outbound_timing(offer: TransportOffer, tz: ZoneInfo, check_in: date) -> Verdict:
    landed = offer.arrives_at.astimezone(tz)
    departs = offer.departs_at
    if landed.date() != check_in:
        return Verdict(
            0.1,
            con=f"прибытие {day_month(landed.date())} в {clock(landed)} — не в день заезда",
            risk="придётся брать лишнюю ночь в отеле или терять ночь заезда",
        )
    hour = landed.hour
    if 11 <= hour < 21:
        score, pro, con = (
            1.0,
            f"удобное время: вылет в {clock(departs)}, прибытие в {clock(landed)}",
            None,
        )
    elif 21 <= hour < 23:
        score, pro, con = 0.7, None, f"прибытие поздно вечером ({clock(landed)})"
    elif hour >= 23 or hour < 6:
        score, pro, con = 0.25, None, f"ночное прибытие ({clock(landed)}): отдых начнётся не сразу"
    else:
        score, pro, con = (
            0.55,
            None,
            f"прибытие утром ({clock(landed)}): до заселения придётся ждать",
        )
    if departs.hour < 6:
        score *= 0.8
        con = f"очень ранний вылет ({clock(departs)})" if con is None else f"{con}; ранний вылет"
        pro = None
    return Verdict(score, pro=pro, con=con)


def _inbound_timing(offer: TransportOffer, tz: ZoneInfo, check_out: date) -> Verdict:
    departs = offer.departs_at.astimezone(tz)
    if departs.date() == check_out + timedelta(days=1) and departs.hour < 6:
        score, pro, con = (
            0.4,
            None,
            f"вылет сразу после полуночи ({clock(departs)}): вечер без номера",
        )
    elif departs.date() != check_out:
        return Verdict(
            0.1,
            con=f"вылет {day_month(departs.date())} в {clock(departs)} — не в день выезда",
            risk="между выселением и вылетом не будет номера или часть ночей пропадёт",
        )
    elif 14 <= departs.hour < 21:
        score, pro, con = 1.0, f"удобное время вылета: {clock(departs)}", None
    elif 12 <= departs.hour < 14:
        score, pro, con = 0.85, None, None
    elif departs.hour >= 21:
        score, pro, con = (
            0.6,
            None,
            f"поздний вылет ({clock(departs)}): после выселения долго ждать",
        )
    elif departs.hour >= 7:
        score, pro, con = 0.6, None, f"ранний вылет ({clock(departs)}): выезд из отеля с утра"
    else:
        score, pro, con = 0.2, None, f"вылет на рассвете ({clock(departs)}): выезд посреди ночи"
    home = offer.arrives_at
    if home.hour >= 23 or home.hour < 5:
        score *= 0.85
        note = f"прилёт домой ночью ({clock(home)})"
        con = note if con is None else f"{con}; {note}"
    return Verdict(score, pro=pro, con=con)


def _baggage(offer: TransportOffer) -> Verdict:
    if offer.baggage_included:
        return Verdict(1.0)
    return Verdict(0.4, con="багаж не включён — доплата при регистрации")


def _fare(offer: TransportOffer) -> Verdict:
    if offer.refundable:
        return Verdict(1.0, pro="возвратный тариф")
    return Verdict(0.5, risk="невозвратный тариф: при изменении планов билет не вернуть")
