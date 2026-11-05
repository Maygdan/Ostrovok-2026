"""Состав группы путешественников: взрослые, дети, питомцы."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from odin.domain.formatting import plural

PetKind = Literal["dog", "cat", "other"]
PET_LABELS: dict[str, str] = {"dog": "собакой", "cat": "кошкой", "other": "питомцем"}

ChildAge = Annotated[int, Field(ge=0, le=17)]
INFANT_MAX_AGE = 1  # до 2 лет в транспорте без отдельного места
CHILD_SEAT_MAX_AGE = 7
CHILD_FARE_SHARE = 0.75  # доля взрослого тарифа за ребёнка от 2 лет


class Party(BaseModel):
    adults: int = Field(2, ge=1, le=9)
    children_ages: list[ChildAge] = Field(default_factory=list, max_length=6)
    pets: list[PetKind] = Field(default_factory=list, max_length=3)

    @property
    def size(self) -> int:
        return self.adults + len(self.children_ages)

    @property
    def paying_seats(self) -> int:
        """Сколько мест оплачивается в транспорте: дети до 2 лет едут на руках бесплатно."""
        return self.adults + sum(age > INFANT_MAX_AGE for age in self.children_ages)

    @property
    def fare_units(self) -> float:
        """Во сколько взрослых билетов обходится дорога: ребёнок 2–17 лет — 75%, младенец — 0."""
        return self.adults + CHILD_FARE_SHARE * (self.paying_seats - self.adults)

    @property
    def has_children(self) -> bool:
        return bool(self.children_ages)

    @property
    def has_pets(self) -> bool:
        return bool(self.pets)

    @property
    def needs_child_seat(self) -> bool:
        return any(age <= CHILD_SEAT_MAX_AGE for age in self.children_ages)

    def label(self) -> str:
        """'2 взрослых + 1 ребёнок (5 лет), с собакой'."""
        parts = [f"{self.adults} {plural(self.adults, 'взрослый', 'взрослых', 'взрослых')}"]
        if self.children_ages:
            n = len(self.children_ages)
            ages = ", ".join(_age_label(age) for age in self.children_ages)
            parts.append(f"{n} {plural(n, 'ребёнок', 'ребёнка', 'детей')} ({ages})")
        text = " + ".join(parts)
        if self.pets:
            text += ", с " + " и ".join(PET_LABELS[pet] for pet in self.pets)
        return text


def _age_label(age: int) -> str:
    return "до года" if age == 0 else f"{age} {plural(age, 'год', 'года', 'лет')}"
