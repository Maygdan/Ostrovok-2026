"""Трансферы между аэропортом или вокзалом и отелем: цена и время считаются от расстояния."""

import math
from datetime import datetime, timedelta

from pydantic import AwareDatetime

from odin.domain.hotel import Hotel
from odin.domain.party import Party
from odin.domain.transfer import HubKind, TransferDirection, TransferKind, TransferOffer

CAR_SEATS = 4
PUBLIC_MAX_KM = 45
MARGIN_MINUTES = 10  # запас, который такси закладывает на подачу и погрузку
SHUTTLE_STEP_MINUTES = 30  # групповой трансфер ходит по расписанию раз в полчаса
NIGHT_SURCHARGE = 1.25


class MockTransfers:
    async def search(
        self,
        hotel: Hotel,
        hub: HubKind,
        direction: TransferDirection,
        when: AwareDatetime,
        party: Party,
    ) -> list[TransferOffer]:
        km = hotel.distance_to_airport_km
        drive = round(12 + km * 1.3)
        if hub is HubKind.STATION:
            km = hotel.distance_to_station_km or 3.0
            drive = round(8 + km * 2.5)
        cars = math.ceil(party.size / CAR_SEATS)
        night = when.hour >= 23 or when.hour < 6
        surcharge = NIGHT_SURCHARGE if night else 1.0

        def offer(
            kind: TransferKind, price: float, minutes: int, **features: bool
        ) -> TransferOffer:
            return TransferOffer(
                kind=kind,
                direction=direction,
                hub=hub,
                pickup_at=_pickup(kind, direction, when, minutes),
                duration_minutes=minutes,
                total_price_rub=int(round(price, -1)),
                **features,
            )

        offers = [
            offer(
                TransferKind.TAXI,
                cars * (700 + 65 * km) * surcharge,
                drive,
                child_seat=True,
                pets_allowed=True,
                meet_and_greet=False,
            ),
            offer(
                TransferKind.PRIVATE,
                cars * (1500 + 110 * km) * surcharge,
                round(drive * 0.95),
                child_seat=True,
                pets_allowed=True,
                meet_and_greet=True,
            ),
            offer(
                TransferKind.SHUTTLE,
                party.fare_units * (150 + 6 * km),
                round(drive * 1.6 + 15),
                child_seat=False,
                pets_allowed=False,
                meet_and_greet=False,
            ),
        ]
        if km <= PUBLIC_MAX_KM:
            offers.append(
                offer(
                    TransferKind.PUBLIC,
                    party.fare_units * (60 + 2 * km),
                    round(drive * 2.2 + 20),
                    child_seat=False,
                    pets_allowed=True,
                    meet_and_greet=False,
                )
            )
        return offers


def _pickup(
    kind: TransferKind, direction: TransferDirection, when: datetime, minutes: int
) -> datetime:
    if direction is TransferDirection.IN:
        if kind is TransferKind.SHUTTLE:
            return _round_up(when, SHUTTLE_STEP_MINUTES)
        return when
    leave = when - timedelta(minutes=minutes + MARGIN_MINUTES)
    if kind is TransferKind.SHUTTLE:
        return leave - timedelta(minutes=leave.minute % SHUTTLE_STEP_MINUTES)
    return leave


def _round_up(moment: datetime, step_minutes: int) -> datetime:
    return moment + timedelta(minutes=-moment.minute % step_minutes)
