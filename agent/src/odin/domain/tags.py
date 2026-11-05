"""Единый словарь признаков: им описываются направления, отели и пожелания пользователя."""

from enum import StrEnum


class Tag(StrEnum):
    BEACH = "beach"
    CITY = "city"
    CULTURE = "culture"
    NATURE = "nature"
    MOUNTAINS = "mountains"
    SKI = "ski"
    NIGHTLIFE = "nightlife"
    SHOPPING = "shopping"
    FAMILY = "family"
    ROMANTIC = "romantic"
    QUIET = "quiet"
    POOL = "pool"
    KIDS_CLUB = "kids_club"
    SPA = "spa"
    BEACHFRONT = "beachfront"
    CENTRAL = "central"
    FAMILY_ROOMS = "family_rooms"


TAG_LABELS: dict[Tag, str] = {
    Tag.BEACH: "пляжный отдых",
    Tag.CITY: "городской отдых",
    Tag.CULTURE: "музеи и достопримечательности",
    Tag.NATURE: "природа",
    Tag.MOUNTAINS: "горы",
    Tag.SKI: "горные лыжи",
    Tag.NIGHTLIFE: "ночная жизнь",
    Tag.SHOPPING: "шопинг",
    Tag.FAMILY: "отдых с детьми",
    Tag.ROMANTIC: "романтика",
    Tag.QUIET: "тихое место",
    Tag.POOL: "бассейн",
    Tag.KIDS_CLUB: "детский клуб",
    Tag.SPA: "спа",
    Tag.BEACHFRONT: "первая линия",
    Tag.CENTRAL: "в центре",
    Tag.FAMILY_ROOMS: "семейные номера",
}

DESTINATION_TAGS = frozenset(
    {
        Tag.BEACH,
        Tag.CITY,
        Tag.CULTURE,
        Tag.NATURE,
        Tag.MOUNTAINS,
        Tag.SKI,
        Tag.NIGHTLIFE,
        Tag.SHOPPING,
        Tag.FAMILY,
        Tag.ROMANTIC,
        Tag.QUIET,
    }
)
HOTEL_TAGS = frozenset(
    {
        Tag.POOL,
        Tag.KIDS_CLUB,
        Tag.SPA,
        Tag.BEACHFRONT,
        Tag.CENTRAL,
        Tag.QUIET,
        Tag.FAMILY_ROOMS,
    }
)


def labels(tags: set[Tag] | frozenset[Tag]) -> str:
    """Человекочитаемый список тегов в стабильном порядке словаря."""
    return ", ".join(TAG_LABELS[tag] for tag in Tag if tag in tags)
