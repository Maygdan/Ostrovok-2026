from datetime import date, timedelta

from tests.factories import make_hotel_offer

TODAY = date(2026, 10, 28)


class TestOfferAsOfToday:
    def test_free_cancellation_that_is_still_open_is_kept(self) -> None:
        offer = make_hotel_offer(free_until=TODAY + timedelta(days=3))

        assert offer.as_of(TODAY) is offer

    def test_the_last_day_of_free_cancellation_still_counts(self) -> None:
        offer = make_hotel_offer(free_until=TODAY)

        assert offer.as_of(TODAY).cancellation.free_until == TODAY

    def test_expired_free_cancellation_makes_the_rate_non_refundable(self) -> None:
        offer = make_hotel_offer(free_until=TODAY - timedelta(days=1))

        today_offer = offer.as_of(TODAY)

        assert not today_offer.cancellation.refundable
        assert offer.cancellation.refundable, "исходное предложение не меняется"
        assert today_offer.model_copy(update={"cancellation": offer.cancellation}) == offer

    def test_rate_that_was_never_refundable_stays_as_it_is(self) -> None:
        offer = make_hotel_offer(free_until=None)

        assert offer.as_of(TODAY) is offer
