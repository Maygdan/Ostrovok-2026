"""Справочник городов и направлений на синтетических данных."""

from collections.abc import Iterable, Sequence
from typing import Self

from odin.domain.destination import Destination
from odin.domain.places import Place
from odin.providers.mock.files import read_json


class MockCatalog:
    def __init__(self, places: Sequence[Place], destinations: Sequence[Destination]) -> None:
        self._destinations = {destination.id: destination for destination in destinations}
        # Направление — тот же город, но с дополнительными данными.
        self._places = {place.id: place for place in places} | self._destinations

    @classmethod
    def from_files(cls) -> Self:
        places = [Place.model_validate(item) for item in read_json("places.json")]
        details = read_json("destinations.json")
        destinations = [
            Destination.model_validate(place.model_dump() | details[place.id])
            for place in places
            if place.id in details
        ]
        return cls(places, destinations)

    async def get_place(self, place_id: str) -> Place | None:
        return self._places.get(place_id)

    async def find_place(self, text: str) -> Place | None:
        return _best_match(text, self._places.values())

    async def get_destination(self, destination_id: str) -> Destination | None:
        return self._destinations.get(destination_id)

    async def find_destination(self, text: str) -> Destination | None:
        return _best_match(text, self._destinations.values())

    async def list_places(self) -> list[Place]:
        return list(self._places.values())

    async def list_destinations(self) -> list[Destination]:
        return list(self._destinations.values())


def _normalize(text: str) -> str:
    return " ".join(text.lower().replace("ё", "е").split())


def _best_match[P: Place](text: str, places: Iterable[P]) -> P | None:
    """Город, чьё название, id или основа названия встречается в тексте; побеждает самое длинное."""
    query = _normalize(text)
    best: P | None = None
    best_length = 0
    for place in places:
        for key in (place.id, place.name, *place.aliases):
            key = _normalize(key)
            if key in query and len(key) > best_length:
                best, best_length = place, len(key)
    return best
