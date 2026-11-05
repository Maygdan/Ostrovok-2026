from datetime import date

import pytest

from odin.providers.interfaces import Providers
from odin.providers.mock import build_mock_providers

TODAY = date(2026, 10, 28)


@pytest.fixture(scope="session")
def providers() -> Providers:
    return build_mock_providers()
