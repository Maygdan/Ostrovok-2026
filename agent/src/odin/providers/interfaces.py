"""Интерфейсы источников данных. Планировщик и агент зависят только от них.

Чтобы подключить реальный источник, реализуйте нужный Protocol и передайте его в Providers.
Все методы асинхронные: настоящие провайдеры ходят в сеть.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from pydantic import AwareDatetime

from odin.domain.destination import Destination, MonthWeather
from odin.domain.hotel import Hotel, HotelOffer
from odin.domain.order import Booking, CartItem, PaymentReceipt
from odin.domain.party import Party
from odin.domain.places import Place
from odin.domain.transfer import HubKind, TransferDirection, TransferOffer
from odin.domain.transport import TransportOffer


class CatalogProvider(Protocol):
    """Справочник городов и направлений."""

    async def get_place(self, place_id: str) -> Place | None: ...

    async def find_place(self, text: str) -> Place | None:
        """Город по свободному тексту («из Питера», «Москвы»)."""
        ...

    async def get_destination(self, destination_id: str) -> Destination | None: ...

    async def find_destination(self, text: str) -> Destination | None: ...

    async def list_places(self) -> list[Place]:
        """Все города каталога: и направления, и пункты вылета."""
        ...

    async def list_destinations(self) -> list[Destination]: ...


class WeatherProvider(Protocol):
    async def month_weather(self, destination: Destination, month: int) -> MonthWeather | None: ...


class HotelProvider(Protocol):
    async def search(
        self, destination: Destination, check_in: date, check_out: date, party: Party
    ) -> list[HotelOffer]:
        """Все доступные тарифы всех отелей направления на даты, с ценой для всей группы."""
        ...


class TransportProvider(Protocol):
    async def search(
        self, origin: Place, destination: Place, day: date, party: Party
    ) -> list[TransportOffer]:
        """Перелёты и поезда в одну сторону, отправляющиеся в указанный день."""
        ...


class TransferProvider(Protocol):
    async def search(
        self,
        hotel: Hotel,
        hub: HubKind,
        direction: TransferDirection,
        when: AwareDatetime,
        party: Party,
    ) -> list[TransferOffer]:
        """Трансферы между аэропортом или вокзалом и отелем.

        Для IN `when` — время, когда группа выйдет из терминала (раньше машина не нужна).
        Для OUT `when` — время, к которому группа должна быть в аэропорту или на вокзале.
        """
        ...


class PaymentProvider(Protocol):
    async def charge(
        self, amount_rub: int, description: str, method: str, idempotency_key: str
    ) -> PaymentReceipt:
        """Списывает сумму. Повтор с тем же ключом не списывает деньги второй раз."""
        ...


class BookingProvider(Protocol):
    async def book(self, items: Sequence[CartItem], order_id: str) -> list[Booking]:
        """Подтверждает у поставщиков каждую позицию оплаченной корзины."""
        ...


@dataclass(frozen=True)
class Providers:
    catalog: CatalogProvider
    weather: WeatherProvider
    hotels: HotelProvider
    transport: TransportProvider
    transfers: TransferProvider
    payments: PaymentProvider
    bookings: BookingProvider
