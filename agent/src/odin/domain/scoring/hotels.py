"""Отели: жёсткие фильтры и критерии сравнения."""

from collections.abc import Sequence
from datetime import date

from odin.domain.destination import Destination
from odin.domain.formatting import day_month, distance, km, nights, rub
from odin.domain.hotel import MEAL_LABELS, MEAL_ORDER, HotelOffer, MealPlan
from odin.domain.ranking import Criterion, Rule, Screened, Verdict, clamp, reject_when, screen
from odin.domain.request import BudgetStyle, TripRequest
from odin.domain.scoring.common import PRICE_WEIGHT, PriceScale, price_verdict
from odin.domain.tags import HOTEL_TAGS, Tag, labels

FAMILY_NEEDS = frozenset({Tag.POOL, Tag.KIDS_CLUB})
FAMILY_AMENITIES_WEIGHT = 2.5  # с ребёнком бассейн и детский клуб важнее обычного
CITY_TAGS = frozenset({Tag.CITY, Tag.CULTURE, Tag.CENTRAL, Tag.SHOPPING, Tag.NIGHTLIFE})
MEAL_BASELINE = {
    MealPlan.RO: 0.3,
    MealPlan.BB: 0.6,
    MealPlan.HB: 0.75,
    MealPlan.FB: 0.85,
    MealPlan.AI: 0.9,
}


def screen_hotels(offers: Sequence[HotelOffer], request: TripRequest) -> Screened[HotelOffer]:
    rules: list[Rule[HotelOffer]] = []
    if request.min_stars is not None:
        stars = request.min_stars
        rules.append(reject_when(f"меньше {stars}★", lambda o: o.hotel.stars < stars))
    if request.free_cancellation:
        rules.append(reject_when("нет бесплатной отмены", lambda o: not o.cancellation.refundable))
    if request.party.has_pets:
        rules.append(reject_when("не принимает животных", lambda o: not o.hotel.pets_allowed))
    if request.budget_total_rub is not None:
        budget = request.budget_total_rub
        rules.append(reject_when("дороже всего бюджета", lambda o: o.total_price_rub > budget))
    return screen(offers, rules)


def hotel_criteria(
    request: TripRequest,
    destination: Destination,
    offers: Sequence[HotelOffer],
    today: date,
) -> list[Criterion[HotelOffer]]:
    scale = PriceScale.of([offer.total_price_rub for offer in offers])
    stars_weight = 1.0 if request.budget_style is BudgetStyle.PREMIUM else 0.5
    amenities_weight = FAMILY_AMENITIES_WEIGHT if request.party.has_children else 1.5
    return [
        Criterion(
            "price",
            PRICE_WEIGHT[request.budget_style],
            lambda o: _price(o, scale, request.budget_style),
        ),
        Criterion("rating", 2.0, _rating),
        Criterion("cancellation", 1.5, lambda o: _cancellation(o, today)),
        Criterion("meal", 1.5, lambda o: _meal(o, request)),
        Criterion("location", 2.0, lambda o: _location(o, request, destination)),
        Criterion("amenities", amenities_weight, lambda o: _amenities(o, request)),
        Criterion("airport", 1.0, _airport),
        Criterion("stars", stars_weight, lambda o: Verdict(o.hotel.stars / 5)),
    ]


def _price(offer: HotelOffer, scale: PriceScale, style: BudgetStyle) -> Verdict:
    best = f"самый выгодный по цене: {rub(offer.total_price_rub)} за {nights(offer.nights)}"
    return price_verdict(offer.total_price_rub, scale, best, style)


def _rating(offer: HotelOffer) -> Verdict:
    rating = offer.hotel.rating
    score = clamp((rating - 6.0) / 4.0)
    if rating >= 8.5:
        return Verdict(score, pro=f"высокий рейтинг гостей {rating:.1f}")
    if rating < 7.5:
        return Verdict(score, con=f"рейтинг гостей {rating:.1f} — ниже среднего")
    return Verdict(score)


def _cancellation(offer: HotelOffer, today: date) -> Verdict:
    free_until = offer.cancellation.free_until
    if free_until is None:
        return Verdict(
            0.2, risk="невозвратный тариф: при изменении планов деньги за отель не вернуть"
        )
    days_left = (free_until - today).days
    if days_left < 0:
        return Verdict(
            0.2, risk="срок бесплатной отмены уже прошёл — тариф фактически невозвратный"
        )
    if days_left < 3:
        return Verdict(
            0.6, risk=f"бесплатная отмена только до {day_month(free_until)} — это совсем скоро"
        )
    return Verdict(1.0, pro=f"бесплатная отмена до {day_month(free_until)}")


def _meal(offer: HotelOffer, request: TripRequest) -> Verdict:
    plan, wanted = offer.meal_plan, request.meal_plan
    label = MEAL_LABELS[plan]
    if wanted is not None:
        gap = MEAL_ORDER.index(plan) - MEAL_ORDER.index(wanted)
        if gap == 0:
            return Verdict(1.0, pro=f"питание как вы хотели: {label}")
        if gap < 0:
            score = clamp(1 + 0.3 * gap)
            return Verdict(score, con=f"питание «{label}», а вы хотели «{MEAL_LABELS[wanted]}»")
        return Verdict(clamp(1 - 0.1 * gap))
    if plan is MealPlan.AI:
        note = (
            "всё включено — с ребёнком не придётся искать, где поесть"
            if request.party.has_children
            else "всё включено: расходы на еду известны заранее"
        )
        return Verdict(MEAL_BASELINE[plan], pro=note)
    if plan is MealPlan.RO:
        return Verdict(MEAL_BASELINE[plan], con="без питания — еду придётся оплачивать отдельно")
    return Verdict(MEAL_BASELINE[plan])


def _location(offer: HotelOffer, request: TripRequest, destination: Destination) -> Verdict:
    hotel = offer.hotel
    verdicts = []
    wants_beach = request.wants_sea or (
        Tag.BEACH in destination.tags and Tag.CITY not in destination.tags
    )
    if wants_beach and hotel.distance_to_beach_m is not None:
        verdicts.append(_beach(hotel.distance_to_beach_m))
    wants_center = bool(CITY_TAGS & (set(destination.tags) | set(request.tags)))
    if wants_center:
        verdicts.append(_center(hotel.distance_to_center_km))
    if not verdicts:
        return Verdict(0.6)
    return Verdict(
        score=sum(v.score for v in verdicts) / len(verdicts),
        pro=next((v.pro for v in verdicts if v.pro), None),
        con=next((v.con for v in verdicts if v.con), None),
    )


def _beach(meters: int) -> Verdict:
    if meters <= 150:
        return Verdict(1.0, pro=f"первая линия: до пляжа {distance(meters)}")
    if meters <= 400:
        return Verdict(0.85, pro=f"до пляжа {distance(meters)} пешком")
    if meters <= 800:
        return Verdict(0.6)
    if meters <= 1500:
        return Verdict(0.35, con=f"до пляжа {distance(meters)} — придётся ехать или долго идти")
    return Verdict(0.15, con=f"до пляжа {distance(meters)} — далеко для пляжного отдыха")


def _center(distance_km: float) -> Verdict:
    if distance_km <= 1.5:
        return Verdict(1.0, pro=f"в центре: до центра {km(distance_km)}")
    if distance_km <= 4:
        return Verdict(0.7)
    if distance_km <= 8:
        return Verdict(0.4, con=f"до центра {km(distance_km)} — придётся ездить")
    return Verdict(0.2, con=f"далеко от центра: {km(distance_km)}")


def _amenities(offer: HotelOffer, request: TripRequest) -> Verdict:
    wanted = {tag for tag in request.tags if tag in HOTEL_TAGS}
    if request.party.has_children:
        wanted |= FAMILY_NEEDS
    if not wanted:
        return Verdict(0.6)
    have = wanted & set(offer.hotel.tags)
    missing = wanted - have
    return Verdict(
        score=len(have) / len(wanted),
        pro=f"есть: {labels(have)}" if have else None,
        con=f"нет: {labels(missing)}" if missing else None,
    )


def _airport(offer: HotelOffer) -> Verdict:
    distance_km = offer.hotel.distance_to_airport_km
    if distance_km <= 15:
        return Verdict(1.0, pro=f"до аэропорта всего {km(distance_km)}")
    if distance_km <= 30:
        return Verdict(0.8)
    if distance_km <= 50:
        return Verdict(0.5)
    return Verdict(0.2, con=f"до аэропорта {km(distance_km)} — долгий трансфер")
