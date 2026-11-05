from odin.domain.ranking import rank
from odin.domain.request import TripRequest
from odin.domain.scoring.transfers import screen_transfers, transfer_criteria
from odin.domain.transfer import TransferDirection, TransferKind, TransferOffer
from tests.factories import CHECK_IN, at, make_request, make_transfer


def transfer(kind: TransferKind, price: int, minutes: int = 45, **fields) -> TransferOffer:
    return make_transfer(
        TransferDirection.IN,
        at(CHECK_IN, "13:05"),
        kind=kind,
        price=price,
        duration_minutes=minutes,
        **fields,
    )


def ranked(offers: list[TransferOffer], request: TripRequest | None = None):
    request = request or make_request()
    return rank(offers, transfer_criteria(request, offers))


def test_taxi_is_preferred_to_a_slow_shuttle_at_a_similar_price() -> None:
    taxi = transfer(TransferKind.TAXI, 3_000)
    shuttle = transfer(TransferKind.SHUTTLE, 2_800, minutes=75, child_seat=False)

    result = ranked([shuttle, taxi])

    assert result[0].option.kind is TransferKind.TAXI
    shuttle_cons = " ".join(result[1].cons)
    assert "групповой" in shuttle_cons
    assert "заметно дольше" in shuttle_cons


def test_with_a_small_child_the_missing_child_seat_decides() -> None:
    request = make_request()
    request.party.children_ages.append(4)
    cheap_no_seat = transfer(TransferKind.TAXI, 2_000, child_seat=False)
    pricey_with_seat = transfer(TransferKind.PRIVATE, 5_000, meet_and_greet=True)

    result = ranked([cheap_no_seat, pricey_with_seat], request)

    assert result[0].option.kind is TransferKind.PRIVATE
    assert any("кресло" in note for note in result[0].pros)
    assert any("без кресла" in note for note in result[1].risks)


def test_child_seat_is_irrelevant_for_adults_only() -> None:
    result = ranked([transfer(TransferKind.TAXI, 2_000, child_seat=False)])

    assert not result[0].risks


def test_public_transport_is_flagged_as_inconvenient_with_kids() -> None:
    request = make_request()
    request.party.children_ages.append(9)
    bus = transfer(TransferKind.PUBLIC, 300, minutes=100, child_seat=False)

    result = ranked([bus], request)

    assert any("детьми" in note for note in result[0].cons)


def test_pets_exclude_carriers_that_do_not_take_them() -> None:
    request = make_request()
    request.party.pets.append("dog")
    ok = transfer(TransferKind.TAXI, 3_000)
    shuttle = transfer(TransferKind.SHUTTLE, 1_000, pets_allowed=False)

    screened = screen_transfers([shuttle, ok], request)

    assert screened.kept == [ok]
