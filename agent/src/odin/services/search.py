"""Поиск вариантов для каждой части поездки: запрос к провайдерам, фильтры и сравнение."""

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta

from odin.domain.dates import DateWindow, resolve_window
from odin.domain.destination import Destination
from odin.domain.errors import DomainError, MissingInformation
from odin.domain.formatting import hours
from odin.domain.hotel import HotelOffer
from odin.domain.junctions import arrives_for_check_in
from odin.domain.party import Party
from odin.domain.places import Place
from odin.domain.plan import Offer, Slot
from odin.domain.ranking import Dropped, Ranked, Screened, rank
from odin.domain.request import TripRequest
from odin.domain.scoring.destinations import (
    DestinationFacts,
    destination_criteria,
    screen_destinations,
)
from odin.domain.scoring.hotels import hotel_criteria, screen_hotels
from odin.domain.scoring.transfers import screen_transfers, transfer_criteria
from odin.domain.scoring.transport import screen_outbound, screen_transport, transport_criteria
from odin.domain.transfer import HubKind, TransferDirection, TransferOffer
from odin.domain.transport import TransportKind, TransportOffer
from odin.providers.interfaces import Providers


@dataclass(frozen=True)
class Trip:
    """Запрос, разобранный до конкретных городов и дат; `today` — дата, на которую идёт поиск."""

    request: TripRequest
    origin: Place
    destination: Destination
    window: DateWindow
    today: date


@dataclass(frozen=True)
class Search[T: Offer]:
    """Результат поиска по одной части: ранжированные варианты и отсеянные с причинами."""

    ranked: list[Ranked[T]]
    dropped: list[Dropped[T]]

    @property
    def reasons(self) -> dict[str, int]:
        return Screened([], self.dropped).reasons

    def find(self, option_id: str) -> Ranked[T] | None:
        return next((item for item in self.ranked if item.option.id == option_id), None)

    def why_dropped(self, option_id: str) -> str | None:
        return next((item.reason for item in self.dropped if item.option.id == option_id), None)

    def require_options(self, what: str) -> None:
        """Объясняет, почему варианты кончились, чтобы пользователю можно было предложить выход."""
        if self.ranked:
            return
        reasons = "; ".join(f"{reason} ({count})" for reason, count in self.reasons.items())
        raise DomainError(
            f"Нет подходящих вариантов: {what}." + (f" Отсеяно: {reasons}." if reasons else "")
        )


@dataclass(frozen=True)
class Excluded:
    destination: Destination
    reason: str


@dataclass(frozen=True)
class DestinationSearch:
    window: DateWindow
    ranked: list[Ranked[DestinationFacts]]
    excluded: list[Excluded]


class TripSearch:
    def __init__(self, providers: Providers) -> None:
        self._providers = providers

    async def resolve_origin(self, request: TripRequest) -> Place:
        if request.origin is None:
            raise MissingInformation("Не указан город вылета.")
        origin = await self._providers.catalog.get_place(request.origin)
        if origin is None:
            raise DomainError(f"Неизвестный город вылета: {request.origin}.")
        return origin

    async def resolve_trip(self, request: TripRequest, today: date) -> Trip:
        origin = await self.resolve_origin(request)
        if request.destination is None:
            raise MissingInformation("Не выбрано направление.")
        destination = await self._providers.catalog.get_destination(request.destination)
        if destination is None:
            raise DomainError(f"Неизвестное направление: {request.destination}.")
        if destination.id == origin.id:
            raise DomainError("Город вылета и направление совпадают.")
        return Trip(request, origin, destination, resolve_window(request, today), today)

    async def destinations(self, request: TripRequest, today: date) -> DestinationSearch:
        """Какие направления подходят под запрос и в каком порядке."""
        origin = await self.resolve_origin(request)
        window = resolve_window(request, today)
        candidates = [
            d for d in await self._providers.catalog.list_destinations() if d.id != origin.id
        ]
        results = await asyncio.gather(
            *(self._destination_facts(d, origin, request, window, today) for d in candidates)
        )
        facts: list[DestinationFacts] = []
        excluded: list[Excluded] = []
        for destination, result in zip(candidates, results, strict=True):
            if isinstance(result, str):
                excluded.append(Excluded(destination, result))
            else:
                facts.append(result)
        screened = screen_destinations(facts, request)
        excluded += [Excluded(item.option.destination, item.reason) for item in screened.dropped]
        if not screened.kept:
            return DestinationSearch(window, [], excluded)
        ranked = rank(screened.kept, destination_criteria(request, screened.kept))
        return DestinationSearch(window, ranked, excluded)

    async def _destination_facts(
        self,
        destination: Destination,
        origin: Place,
        request: TripRequest,
        window: DateWindow,
        today: date,
    ) -> DestinationFacts | str:
        """Факты для сравнения направления или причина, по которой его нельзя предложить."""
        party = request.party
        providers = self._providers
        weather, outbound, inbound, stays = await asyncio.gather(
            providers.weather.month_weather(destination, window.check_in.month),
            self._outbound_offers(origin, destination, window.check_in, party, today),
            providers.transport.search(destination, origin, window.check_out, party),
            providers.hotels.search(destination, window.check_in, window.check_out, party),
        )
        if weather is None:
            return "нет данных о погоде"
        allowed = [o for o in outbound if o.kind in request.transport_kinds]
        if not allowed:
            return "нет рейсов или поездов нужного вида"
        fastest = min(offer.duration_minutes for offer in allowed)
        limit = request.max_travel_hours
        if limit is not None and fastest > round(limit * 60):
            return f"дорога от {hours(fastest / 60)}, а вы просили не дольше {hours(limit)}"

        legs = (
            ("дорога туда", screen_outbound(outbound, request, window.check_in, destination.tz)),
            ("дорога обратно", screen_transport(inbound, request)),
            ("отели", screen_hotels([stay.as_of(today) for stay in stays], request)),
        )
        for label, screened in legs:
            if not screened.kept:
                reasons = max(screened.reasons.items(), key=lambda item: item[1], default=None)
                return f"{label}: {reasons[0] if reasons else 'нет вариантов'}"
        price = sum(min(o.total_price_rub for o in screened.kept) for _, screened in legs)
        return DestinationFacts(destination, weather, fastest, price)

    async def hotels(self, trip: Trip) -> Search[HotelOffer]:
        window, request = trip.window, trip.request
        offers = await self._providers.hotels.search(
            trip.destination, window.check_in, window.check_out, request.party
        )
        screened = screen_hotels([offer.as_of(trip.today) for offer in offers], request)
        if not screened.kept:
            return Search([], screened.dropped)
        criteria = hotel_criteria(request, trip.destination, screened.kept, trip.today)
        return Search(rank(screened.kept, criteria), screened.dropped)

    async def transport(self, trip: Trip, slot: Slot) -> Search[TransportOffer]:
        """Дорога туда (к заезду) или обратно (в день выезда)."""
        request, tz = trip.request, trip.destination.tz
        if slot is Slot.OUTBOUND:
            day = trip.window.check_in
            offers = await self._outbound_offers(
                trip.origin, trip.destination, day, request.party, trip.today
            )
            screened = screen_outbound(offers, request, day, tz)
        else:
            day = trip.window.check_out
            offers = await self._providers.transport.search(
                trip.destination, trip.origin, day, request.party
            )
            screened = screen_transport(offers, request)
        if not screened.kept:
            return Search([], screened.dropped)
        criteria = transport_criteria(request, screened.kept, slot, tz, day)
        return Search(rank(screened.kept, criteria), screened.dropped)

    async def _outbound_offers(
        self, origin: Place, destination: Destination, check_in: date, party: Party, today: date
    ) -> list[TransportOffer]:
        """Рейсы и поезда в той дате вылета, при которой они прибывают к заезду.

        Ночной поезд или дальний перелёт вылетает накануне заезда, дневной рейс — в его день.
        У ежедневного рейса один номер в обе даты, поэтому из двух вылетов берётся подходящий;
        если не подходит ни один, остаётся вылет в день заезда, и поиск отсеет его с причиной.
        Вчерашний день не ищется: вылететь в прошлое нельзя.
        """
        yesterday = check_in - timedelta(days=1)
        days = [day for day in (yesterday, check_in) if day >= today]
        results = await asyncio.gather(
            *(self._providers.transport.search(origin, destination, day, party) for day in days)
        )
        found = dict(zip(days, results, strict=True))

        def fits(offer: TransportOffer) -> bool:
            return arrives_for_check_in(offer.arrives_at.astimezone(destination.tz), check_in)

        offers = {offer.id: offer for offer in found.get(yesterday, []) if fits(offer)}
        for offer in found[check_in]:
            if fits(offer) or offer.id not in offers:
                offers[offer.id] = offer
        return list(offers.values())

    async def transfers(
        self, trip: Trip, slot: Slot, transport: TransportOffer, hotel: HotelOffer
    ) -> Search[TransferOffer]:
        """Трансфер под время конкретного рейса или поезда и конкретный отель."""
        tz = trip.destination.tz
        hub = HubKind.STATION if transport.kind is TransportKind.TRAIN else HubKind.AIRPORT
        if slot is Slot.TRANSFER_IN:
            direction = TransferDirection.IN
            when = transport.arrives_at.astimezone(tz) + transport.arrival_buffer
        else:
            direction = TransferDirection.OUT
            when = transport.departs_at.astimezone(tz) - transport.departure_buffer
        offers = await self._providers.transfers.search(
            hotel.hotel, hub, direction, when, trip.request.party
        )
        screened = screen_transfers(offers, trip.request)
        if not screened.kept:
            return Search([], screened.dropped)
        criteria = transfer_criteria(trip.request, screened.kept)
        return Search(rank(screened.kept, criteria), screened.dropped)
