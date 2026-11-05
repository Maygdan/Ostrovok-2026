"""Проверка стыковок плана: прилёт, заселение, трансферы, выезд и вылет обратно.

Все времена сравниваются в часовом поясе направления: заселение, выселение и стойка
регистрации живут по местному времени, а рейсы приходят в поясах своих аэропортов.
"""

from datetime import date, datetime, time, timedelta

from odin.domain.formatting import clock, day_month, duration, rub
from odin.domain.hotel import HotelOffer
from odin.domain.plan import Issue, IssueCode, Offer, Severity, Slot, TripPlan
from odin.domain.timeutil import to_minutes
from odin.domain.transport import TransportOffer

LONG_WAIT_FOR_CHECK_IN = timedelta(hours=3)
LONG_GAP_AFTER_CHECK_OUT = timedelta(hours=6)
NIGHT_STARTS = time(23, 0)
NIGHT_ENDS = time(6, 0)
DEEP_NIGHT_ENDS = time(5, 0)  # выезд из отеля раньше этого часа считается ночным
MIN_LAYOVER_MINUTES = {False: 60, True: 90}  # ключ — международный ли рейс
MAX_LAYOVER_MINUTES = 6 * 60


def check_plan(plan: TripPlan) -> list[Issue]:
    """Все найденные проблемы и предупреждения. ERROR означает, что оформлять план нельзя."""
    checks = (_stay, _arrival, _departure, _layovers, _party, _budget, _entry_rules)
    return [issue for check in checks for issue in check(plan)]


def _issue(severity: Severity, code: IssueCode, message: str, *slots: Slot) -> Issue:
    return Issue(severity=severity, code=code, message=message, slots=list(slots))


def _stay(plan: TripPlan) -> list[Issue]:
    hotel = plan.hotel
    if hotel is None or (hotel.check_in, hotel.check_out) == (plan.check_in, plan.check_out):
        return []
    return [
        _issue(
            Severity.ERROR,
            IssueCode.STAY_MISMATCH,
            f"Отель забронирован на {day_month(hotel.check_in)} – {day_month(hotel.check_out)}, "
            f"а поездка на {day_month(plan.check_in)} – {day_month(plan.check_out)}.",
            Slot.HOTEL,
        )
    ]


def _arrival(plan: TripPlan) -> list[Issue]:
    """Дорога туда → трансфер → заселение."""
    outbound, hotel = plan.outbound, plan.hotel
    if outbound is None or hotel is None:
        return []
    tz = plan.destination.tz
    landed = outbound.arrives_at.astimezone(tz)
    ready = landed + outbound.arrival_buffer  # когда группа выйдет из терминала
    issues = _arrival_date_issues(landed, hotel.check_in)

    at_hotel = ready
    if (transfer := plan.transfer_in) is not None:
        if transfer.pickup_at < ready:
            issues.append(
                _issue(
                    Severity.ERROR,
                    IssueCode.TRANSFER_BEFORE_LANDING,
                    f"Трансфер подан в {clock(transfer.pickup_at.astimezone(tz))}, а группа "
                    f"выйдет из терминала не раньше {clock(ready)} (прибытие в {clock(landed)}).",
                    Slot.TRANSFER_IN,
                    Slot.OUTBOUND,
                )
            )
        at_hotel = transfer.arrive_at.astimezone(tz)
    return issues + _hotel_arrival_issues(hotel, at_hotel)


def arrives_for_check_in(landed: datetime, check_in_day: date) -> bool:
    """Прибытие приходится на сутки заезда: с утра дня заезда до утра следующего дня.

    `landed` — время прибытия в часовом поясе направления. Раньше номера ещё нет (прошлая
    ночь не оплачена), позже — зря оплачены первые ночи. Сутки заезда начинаются с утра, а не
    с полуночи: ночной прилёт в день заезда оставляет полдня без номера, а прилёт после
    полуночи за днём заезда приходится на уже оплаченную ночь.
    """
    start = datetime.combine(check_in_day, NIGHT_ENDS, tzinfo=landed.tzinfo)
    return start <= landed < start + timedelta(days=1)


def _just_after_midnight(landed: datetime, check_in_day: date) -> bool:
    return landed.date() == check_in_day + timedelta(days=1) and landed.time() < NIGHT_ENDS


def _arrival_date_issues(landed: datetime, check_in_day: date) -> list[Issue]:
    if landed.date() == check_in_day:
        return []
    slots = (Slot.OUTBOUND, Slot.HOTEL)
    if landed.date() < check_in_day:
        return [
            _issue(
                Severity.ERROR,
                IssueCode.ARRIVES_BEFORE_CHECK_IN,
                f"Прибытие {day_month(landed.date())}, а заезд в отель {day_month(check_in_day)}: "
                "нужна дополнительная ночь или другой рейс.",
                *slots,
            )
        ]
    if _just_after_midnight(landed, check_in_day):
        return [
            _issue(
                Severity.WARNING,
                IssueCode.LATE_ARRIVAL,
                f"Прибытие в {clock(landed)} уже после полуночи: номер за ночь заезда оплачен, "
                "но заселение будет глубокой ночью — предупредите отель.",
                *slots,
            )
        ]
    return [
        _issue(
            Severity.ERROR,
            IssueCode.ARRIVES_AFTER_CHECK_IN,
            f"Прибытие {day_month(landed.date())} в {clock(landed)}, а заезд в отель "
            f"{day_month(check_in_day)}: первые ночи оплачены зря.",
            *slots,
        )
    ]


def _hotel_arrival_issues(offer: HotelOffer, at_hotel: datetime) -> list[Issue]:
    issues = []
    opens = datetime.combine(offer.check_in, offer.hotel.check_in_from, tzinfo=at_hotel.tzinfo)
    wait = opens - at_hotel
    if wait > LONG_WAIT_FOR_CHECK_IN:
        issues.append(
            _issue(
                Severity.WARNING,
                IssueCode.WAIT_FOR_CHECK_IN,
                f"В отель вы приедете около {clock(at_hotel)}, а заселение с "
                f"{offer.hotel.check_in_from:%H:%M}: ждать {duration(to_minutes(wait))}. "
                "Ранний заезд не гарантирован — уточните его или оставьте багаж на хранение.",
                Slot.HOTEL,
                Slot.TRANSFER_IN,
            )
        )
    is_night = at_hotel.time() >= NIGHT_STARTS or at_hotel.time() < NIGHT_ENDS
    if is_night and not offer.hotel.reception_24h:
        issues.append(
            _issue(
                Severity.WARNING,
                IssueCode.NIGHT_ARRIVAL_AT_HOTEL,
                f"В отель вы приедете в {clock(at_hotel)}, а стойка регистрации работает не "
                "круглосуточно — договоритесь о позднем заезде заранее.",
                Slot.HOTEL,
                Slot.TRANSFER_IN,
            )
        )
    return issues


def _departure(plan: TripPlan) -> list[Issue]:
    """Выселение → трансфер → дорога обратно."""
    inbound, hotel = plan.inbound, plan.hotel
    if inbound is None or hotel is None:
        return []
    tz = plan.destination.tz
    departs = inbound.departs_at.astimezone(tz)
    issues = _departure_date_issues(departs, hotel.check_out)
    if any(issue.severity is Severity.ERROR for issue in issues):
        return issues

    must_reach_hub = departs - inbound.departure_buffer
    leaves_hotel = must_reach_hub
    if (transfer := plan.transfer_out) is not None:
        leaves_hotel = transfer.pickup_at.astimezone(tz)
        arrives_at_hub = transfer.arrive_at.astimezone(tz)
        if arrives_at_hub > must_reach_hub:
            issues.append(
                _issue(
                    Severity.ERROR,
                    IssueCode.MISSED_DEPARTURE,
                    f"Трансфер выезжает в {clock(leaves_hotel)} и довезёт к "
                    f"{clock(arrives_at_hub)}, а быть на месте нужно к {clock(must_reach_hub)} "
                    f"(отправление в {clock(departs)}).",
                    Slot.TRANSFER_OUT,
                    Slot.INBOUND,
                )
            )
    if leaves_hotel.date() == hotel.check_out and leaves_hotel.time() < DEEP_NIGHT_ENDS:
        issues.append(
            _issue(
                Severity.WARNING,
                IssueCode.NIGHT_PICKUP,
                f"Выезд из отеля в {clock(leaves_hotel)} — посреди ночи, последняя ночь будет "
                "короткой.",
                Slot.TRANSFER_OUT,
                Slot.INBOUND,
            )
        )
    closes = datetime.combine(hotel.check_out, hotel.hotel.check_out_until, tzinfo=tz)
    gap = leaves_hotel - closes
    if gap > LONG_GAP_AFTER_CHECK_OUT:
        issues.append(
            _issue(
                Severity.WARNING,
                IssueCode.LONG_GAP_AFTER_CHECK_OUT,
                f"Выселение в {hotel.hotel.check_out_until:%H:%M}, а выезд в аэропорт только в "
                f"{clock(leaves_hotel)}: около {duration(to_minutes(gap))} без номера. "
                "Попросите поздний выезд или камеру хранения.",
                Slot.HOTEL,
                Slot.INBOUND,
            )
        )
    return issues


def _departure_date_issues(departs: datetime, check_out_day: date) -> list[Issue]:
    if departs.date() == check_out_day:
        return []
    slots = (Slot.INBOUND, Slot.HOTEL)
    if departs.date() < check_out_day:
        return [
            _issue(
                Severity.ERROR,
                IssueCode.DEPARTS_BEFORE_CHECK_OUT,
                f"Обратный рейс {day_month(departs.date())}, а выезд из отеля "
                f"{day_month(check_out_day)}: последние ночи оплачены зря.",
                *slots,
            )
        ]
    if departs.date() == check_out_day + timedelta(days=1) and departs.time() < NIGHT_ENDS:
        return []  # вылет сразу после полуночи: вечер без номера учтёт проверка паузы
    return [
        _issue(
            Severity.ERROR,
            IssueCode.DEPARTS_AFTER_CHECK_OUT,
            f"Обратный рейс {day_month(departs.date())}, а выезд из отеля "
            f"{day_month(check_out_day)}: между выселением и вылетом будет ночь без номера.",
            *slots,
        )
    ]


def _layovers(plan: TripPlan) -> list[Issue]:
    issues = []
    for slot in (Slot.OUTBOUND, Slot.INBOUND):
        offer = plan.get(slot)
        if isinstance(offer, TransportOffer):
            issues += _layover_issues(offer, slot)
    return issues


def _layover_issues(offer: TransportOffer, slot: Slot) -> list[Issue]:
    issues = []
    minimum = MIN_LAYOVER_MINUTES[offer.international]
    for minutes, segment in zip(offer.layovers_minutes, offer.segments, strict=False):
        if minutes < minimum:
            message = (
                f"Пересадка в {segment.destination} всего {duration(minutes)}: при задержке "
                "первого рейса можно не успеть на второй."
            )
            issues.append(_issue(Severity.WARNING, IssueCode.SHORT_LAYOVER, message, slot))
        elif minutes > MAX_LAYOVER_MINUTES:
            message = (
                f"Пересадка в {segment.destination} {duration(minutes)} — это долго, "
                "особенно с детьми."
            )
            issues.append(_issue(Severity.WARNING, IssueCode.LONG_LAYOVER, message, slot))
    return issues


def _party(plan: TripPlan) -> list[Issue]:
    issues = []
    party, hotel = plan.party, plan.hotel
    if hotel is not None and hotel.rooms * hotel.capacity_per_room < party.size:
        issues.append(
            _issue(
                Severity.ERROR,
                IssueCode.NOT_ENOUGH_ROOM,
                f"В {hotel.rooms} номерах отеля помещается {hotel.rooms * hotel.capacity_per_room} "
                f"гостей, а вас {party.size}.",
                Slot.HOTEL,
            )
        )
    if party.has_pets:
        for slot in Slot:
            offer = plan.get(slot)
            if offer is not None and not _allows_pets(offer):
                message = f"«{offer.title}» не принимает животных, а вы едете с питомцем."
                issues.append(_issue(Severity.ERROR, IssueCode.PETS_NOT_ALLOWED, message, slot))
    return issues


def _allows_pets(offer: Offer) -> bool:
    return offer.hotel.pets_allowed if isinstance(offer, HotelOffer) else offer.pets_allowed


def _budget(plan: TripPlan) -> list[Issue]:
    budget = plan.built_for.budget_total_rub
    if budget is None or plan.total_price_rub <= budget:
        return []
    return [
        _issue(
            Severity.ERROR,
            IssueCode.OVER_BUDGET,
            f"Итого {rub(plan.total_price_rub)} — на {rub(plan.total_price_rub - budget)} "
            f"больше бюджета {rub(budget)}.",
        )
    ]


def _entry_rules(plan: TripPlan) -> list[Issue]:
    destination = plan.destination
    if not destination.entry_note:
        return []
    severity = Severity.WARNING if destination.visa_required else Severity.INFO
    return [_issue(severity, IssueCode.VISA, f"Въезд: {destination.entry_note}")]
