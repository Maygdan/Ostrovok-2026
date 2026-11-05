"""Мок-провайдеры на синтетических данных. Все цены, рейсы и отели вымышлены."""

from odin.providers.interfaces import Providers
from odin.providers.mock.catalog import MockCatalog
from odin.providers.mock.checkout import MockBookings, MockPayments
from odin.providers.mock.hotels import MockHotels
from odin.providers.mock.transfers import MockTransfers
from odin.providers.mock.transport import MockTransport
from odin.providers.mock.weather import MockWeather


def build_mock_providers() -> Providers:
    return Providers(
        catalog=MockCatalog.from_files(),
        weather=MockWeather.from_files(),
        hotels=MockHotels.from_files(),
        transport=MockTransport.from_files(),
        transfers=MockTransfers(),
        payments=MockPayments(),
        bookings=MockBookings(),
    )
