from datetime import timedelta

from odin.domain.plan import Slot
from odin.domain.ranking import Ranked, rank
from odin.domain.request import TripRequest
from odin.domain.scoring.transport import (
    screen_outbound,
    screen_transport,
    transport_criteria,
)
from odin.domain.transport import TransportKind, TransportOffer
from tests.factories import (
    ANTALYA,
    CHECK_IN,
    CHECK_OUT,
    MSK,
    at,
    make_connection,
    make_flight,
    make_request,
)


def ranked_transport(
    offers: list[TransportOffer],
    slot: Slot = Slot.OUTBOUND,
    request: TripRequest | None = None,
) -> list[Ranked]:
    day = CHECK_IN if slot is Slot.OUTBOUND else CHECK_OUT
    criteria = transport_criteria(request or make_request(), offers, slot, ANTALYA.tz, day)
    return rank(offers, criteria)


def flight(
    departs: str, arrives: str, number: str, price: int = 30_000, **fields
) -> TransportOffer:
    return make_flight(
        at(CHECK_IN, departs, MSK), at(CHECK_IN, arrives), number=number, price=price, **fields
    )


def explanation_of(ranked: list[Ranked], number: str):
    return next(r for r in ranked if r.option.id == number).explanation()


def test_daytime_arrival_beats_night_arrival_at_the_same_price() -> None:
    day = flight("08:30", "12:05", "DAY1")
    night = flight("00:30", "04:05", "NIGHT1")

    ranked = ranked_transport([night, day])

    assert [r.option.id for r in ranked] == ["DAY1", "NIGHT1"]
    assert any("удобное время" in note for note in explanation_of(ranked, "DAY1").pros)
    cons = " ".join(explanation_of(ranked, "NIGHT1").cons)
    assert "ночное прибытие" in cons
    assert "ранний вылет" in cons


def test_flight_landing_on_the_next_day_is_marked_as_a_risk() -> None:
    next_day = make_flight(
        at(CHECK_IN, "21:00", MSK), at(CHECK_IN + timedelta(days=1), "00:35"), number="LATE1"
    )

    explanation = ranked_transport([next_day])[0].explanation()

    assert any("не в день заезда" in note for note in explanation.cons)
    assert explanation.risks


def test_connection_is_cheaper_but_costs_time_and_a_short_layover_is_risky() -> None:
    direct = flight("08:30", "12:05", "DIRECT1", price=40_000)
    connection = make_connection(layover_minutes=50, price=24_000)

    ranked = ranked_transport([direct, connection])

    direct_notes = explanation_of(ranked, "DIRECT1")
    assert "без пересадок" in direct_notes.pros
    connection_notes = explanation_of(ranked, "SE100+BA200")
    assert any("1 пересадка" in note for note in connection_notes.cons)
    assert any("пересадка всего 50 мин" in note for note in connection_notes.risks)
    assert any("дольше самого быстрого" in note for note in connection_notes.cons)


def test_no_pro_for_direct_flight_when_everything_is_direct() -> None:
    only = flight("08:30", "12:05", "ONLY1")

    assert "без пересадок" not in ranked_transport([only])[0].pros


def test_inbound_flight_at_dawn_is_penalised_against_afternoon_one() -> None:
    afternoon = make_flight(at(CHECK_OUT, "15:40"), at(CHECK_OUT, "21:00", MSK), number="PM1")
    dawn = make_flight(at(CHECK_OUT, "04:40"), at(CHECK_OUT, "08:00", MSK), number="AM1")

    ranked = ranked_transport([dawn, afternoon], Slot.INBOUND)

    assert ranked[0].option.id == "PM1"
    assert any("на рассвете" in note for note in explanation_of(ranked, "AM1").cons)


def test_missing_baggage_and_non_refundable_fare_are_called_out() -> None:
    bare = flight("08:30", "12:05", "BARE1", baggage_included=False)

    explanation = ranked_transport([bare])[0].explanation()

    assert any("багаж не включён" in note for note in explanation.cons)
    assert any("невозвратный" in note for note in explanation.risks)


class TestScreening:
    def test_flights_longer_than_the_limit_are_dropped(self) -> None:
        short = flight("08:30", "12:05", "SHORT1")  # 3 ч 35 мин
        long = flight("08:30", "18:05", "LONG1")  # 9 ч 35 мин
        request = make_request(max_travel_hours=5)

        screened = screen_transport([long, short], request)

        assert screened.kept == [short]
        assert screened.reasons == {"в пути дольше 5 ч": 1}

    def test_transport_kind_filter(self) -> None:
        request = make_request(transport_kinds=[TransportKind.TRAIN])

        screened = screen_transport([flight("08:30", "12:05", "FL1")], request)

        assert screened.kept == []

    def test_pets_need_carrier_permission(self) -> None:
        request = make_request()
        request.party.pets.append("cat")
        allowed = flight("08:30", "12:05", "PET1", pets_allowed=True)
        denied = flight("09:30", "13:05", "NOPET1")

        assert screen_transport([denied, allowed], request).kept == [allowed]

    def test_nonstop_wish_is_a_hard_filter_and_a_limit_counts_stops(self) -> None:
        direct = flight("08:30", "12:05", "DIRECT1")
        connection = make_connection(layover_minutes=90)

        nonstop = screen_transport([direct, connection], make_request(max_stops=0))
        one_stop = screen_transport([direct, connection], make_request(max_stops=1))

        assert nonstop.kept == [direct]
        assert nonstop.reasons == {"есть пересадки": 1}
        assert one_stop.kept == [direct, connection]
        assert screen_transport([connection], make_request(max_stops=0)).kept == []

    def test_outbound_must_land_within_the_check_in_day(self) -> None:
        day = CHECK_IN
        before = day - timedelta(days=1)
        daytime = flight("08:30", "12:05", "DAY1")
        overnight = make_flight(at(before, "14:00", MSK), at(day, "08:10"), number="LONG1")
        too_late = make_flight(
            at(day, "18:00", MSK), at(day + timedelta(days=1), "09:00"), number="LATE1"
        )
        red_eye = make_flight(at(before, "22:00", MSK), at(day, "04:30"), number="NIGHT1")

        screened = screen_outbound(
            [daytime, overnight, too_late, red_eye], make_request(), day, ANTALYA.tz
        )

        assert [offer.id for offer in screened.kept] == ["DAY1", "LONG1"]
        assert screened.reasons == {"прибывает не к заезду": 2}

    def test_outbound_screening_keeps_the_common_rules(self) -> None:
        long = flight("08:30", "18:05", "LONG1")  # 9 ч 35 мин, зато прибывает в день заезда

        screened = screen_outbound([long], make_request(max_travel_hours=5), CHECK_IN, ANTALYA.tz)

        assert screened.kept == []
        assert screened.reasons == {"в пути дольше 5 ч": 1}
