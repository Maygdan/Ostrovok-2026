"""Направления: жёсткие фильтры и критерии сравнения."""

from collections.abc import Sequence
from dataclasses import dataclass

from odin.domain.destination import Destination, MonthWeather
from odin.domain.formatting import duration, hours, rub, temperature
from odin.domain.ranking import Criterion, Rule, Screened, Verdict, clamp, reject_when, screen
from odin.domain.request import BudgetStyle, TripRequest
from odin.domain.scoring.common import PRICE_WEIGHT, PriceScale, price_verdict
from odin.domain.tags import DESTINATION_TAGS, Tag, labels

DEFAULT_SEA_C = 20  # желаемая температура воды, если море нужно, а порог не назван
DEFAULT_AIR_C = 22
COLD_WATER_MARGIN = 5  # насколько вода может быть холоднее желаемого, пока вариант не отсеян
COMFORTABLE_C = 24  # «приятная» температура, если пожеланий по погоде нет
HOT_C = 36


@dataclass(frozen=True)
class DestinationFacts:
    """Факты о направлении для выбранных дат, на которых строится сравнение."""

    destination: Destination
    weather: MonthWeather
    travel_minutes: int  # самый быстрый путь в одну сторону
    price_from_rub: int  # самый дешёвый путь туда-обратно + самый дешёвый подходящий отель


def _wanted_sea(request: TripRequest) -> int:
    return DEFAULT_SEA_C if request.min_sea_temp_c is None else request.min_sea_temp_c


def _wanted_air(request: TripRequest) -> int | None:
    if request.min_air_temp_c is not None:
        return request.min_air_temp_c
    return DEFAULT_AIR_C if request.wants_sea else None


def screen_destinations(
    facts: Sequence[DestinationFacts], request: TripRequest
) -> Screened[DestinationFacts]:
    rules: list[Rule[DestinationFacts]] = []
    if request.wants_sea:
        threshold = _wanted_sea(request)
        rules.append(reject_when("нет моря", lambda f: f.weather.sea_c is None))
        rules.append(
            reject_when(
                f"вода холоднее {temperature(threshold - COLD_WATER_MARGIN)} — купаться нельзя",
                lambda f: (
                    f.weather.sea_c is not None and f.weather.sea_c < threshold - COLD_WATER_MARGIN
                ),
            )
        )
    if request.max_travel_hours is not None:
        limit = round(request.max_travel_hours * 60)
        reason = f"дорога дольше {hours(request.max_travel_hours)}"
        rules.append(reject_when(reason, lambda f: f.travel_minutes > limit))
    if request.budget_total_rub is not None:
        budget = request.budget_total_rub
        rules.append(reject_when("дороже всего бюджета", lambda f: f.price_from_rub > budget))
    if Tag.SKI in request.tags:
        rules.append(
            reject_when("нет горнолыжных трасс", lambda f: Tag.SKI not in f.destination.tags)
        )
    return screen(facts, rules)


def destination_criteria(
    request: TripRequest, facts: Sequence[DestinationFacts]
) -> list[Criterion[DestinationFacts]]:
    scale = PriceScale.of([fact.price_from_rub for fact in facts])
    quickest = min(fact.travel_minutes for fact in facts)
    return [
        Criterion("weather", 3.0, lambda f: _weather(f.weather, request)),
        Criterion(
            "price",
            PRICE_WEIGHT[request.budget_style],
            lambda f: _price(f, scale, request.budget_style),
        ),
        Criterion("travel", 2.0, lambda f: _travel(f, quickest)),
        Criterion("fit", 2.0, lambda f: _fit(f.destination, request)),
        Criterion("entry", 0.5, lambda f: _entry(f.destination)),
    ]


def _weather(weather: MonthWeather, request: TripRequest) -> Verdict:
    parts: list[float] = []
    pros: list[str] = []
    cons: list[str] = []

    if request.wants_sea and weather.sea_c is not None:
        wanted = _wanted_sea(request)
        parts.append(clamp(1 - max(0, wanted - weather.sea_c) / 6))
        if weather.sea_c >= wanted:
            pros.append(f"вода {temperature(weather.sea_c)}")
        else:
            cons.append(
                f"вода {temperature(weather.sea_c)} — прохладнее желаемых {temperature(wanted)}"
            )

    air_floor = _wanted_air(request)
    if air_floor is not None:
        parts.append(clamp(1 - max(0, air_floor - weather.day_c) / 10))
        if weather.day_c >= air_floor:
            pros.append(f"днём {temperature(weather.day_c)}")
        else:
            cons.append(
                f"днём всего {temperature(weather.day_c)} — "
                f"прохладнее желаемых {temperature(air_floor)}"
            )

    if not parts:
        parts.append(clamp(1 - abs(weather.day_c - COMFORTABLE_C) / 20))
    score = sum(parts) / len(parts)

    if weather.day_c >= HOT_C:
        score *= 0.7
        cons.append(f"жара {temperature(weather.day_c)}")
    if weather.rain_days >= 12:
        score *= 0.8
        cons.append(f"дождливо: {weather.rain_days} дней с осадками в месяце")
    elif weather.rain_days <= 3 and request.wants_sea:
        pros.append("почти без дождей")
    return Verdict(score, pro=", ".join(pros) or None, con="; ".join(cons) or None)


def _price(fact: DestinationFacts, scale: PriceScale, style: BudgetStyle) -> Verdict:
    best = f"самое доступное направление: от {rub(fact.price_from_rub)}"
    return price_verdict(fact.price_from_rub, scale, best, style)


def _travel(fact: DestinationFacts, quickest: int) -> Verdict:
    score = quickest / fact.travel_minutes
    if fact.travel_minutes <= 4 * 60:
        return Verdict(score, pro=f"недолго добираться: {duration(fact.travel_minutes)} в пути")
    if fact.travel_minutes >= 7 * 60:
        return Verdict(score, con=f"долгая дорога: {duration(fact.travel_minutes)} в одну сторону")
    return Verdict(score)


def _fit(destination: Destination, request: TripRequest) -> Verdict:
    tags = set(destination.tags)
    scores: list[float] = []
    pros: list[str] = []
    cons: list[str] = []

    wanted = {tag for tag in request.tags if tag in DESTINATION_TAGS}
    if wanted:
        have = wanted & tags
        scores.append(len(have) / len(wanted))
        if have:
            pros.append(f"подходит под пожелания: {labels(have)}")
        if wanted - have:
            cons.append(f"нет: {labels(wanted - have)}")
    if request.party.has_children:
        if Tag.FAMILY in tags:
            scores.append(1.0)
            pros.append("подходит для отдыха с детьми")
        else:
            scores.append(0.3)
            cons.append("не лучший выбор для отдыха с детьми")
    score = sum(scores) / len(scores) if scores else 0.6
    return Verdict(score, pro="; ".join(pros) or None, con="; ".join(cons) or None)


def _entry(destination: Destination) -> Verdict:
    if destination.visa_required:
        return Verdict(0.4, con=f"нужна виза: {destination.entry_note}".rstrip(": "))
    return Verdict(1.0)
