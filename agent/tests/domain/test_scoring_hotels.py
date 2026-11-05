from datetime import date, timedelta

from odin.domain.hotel import HotelOffer, MealPlan
from odin.domain.plan import Explanation
from odin.domain.ranking import Ranked, rank
from odin.domain.request import BudgetStyle, TripRequest
from odin.domain.scoring.hotels import hotel_criteria, screen_hotels
from odin.domain.tags import Tag
from tests.factories import ANTALYA, CHECK_IN, make_hotel, make_hotel_offer, make_request

TODAY = date(2026, 10, 28)


def ranked_hotels(offers: list[HotelOffer], request: TripRequest | None = None) -> list[Ranked]:
    request = request or make_request()
    return rank(offers, hotel_criteria(request, ANTALYA, offers, TODAY))


def offer(hotel_id: str, price: int, **hotel_fields) -> HotelOffer:
    hotel = make_hotel(id=hotel_id, name=hotel_id, **hotel_fields)
    return make_hotel_offer(hotel=hotel, price=price, rate_id=f"{hotel_id}-rate")


def explain(ranked: list[Ranked], hotel_id: str) -> Explanation:
    return next(r for r in ranked if r.option.hotel.id == hotel_id).explanation()


def test_free_cancellation_wish_drops_non_refundable_rates() -> None:
    flexible = make_hotel_offer(hotel=make_hotel(id="a", name="a"), free_until=CHECK_IN)
    saver = make_hotel_offer(hotel=make_hotel(id="b", name="b"), free_until=None, rate_id="saver")

    screened = screen_hotels([flexible, saver], make_request(free_cancellation=True))

    assert screened.kept == [flexible]
    assert screened.reasons == {"нет бесплатной отмены": 1}
    assert screen_hotels([flexible, saver], make_request()).kept == [flexible, saver]


def test_hotel_near_the_beach_beats_a_far_one_when_everything_else_is_equal() -> None:
    near = offer("near", 80_000, distance_to_beach_m=100)
    far = offer("far", 80_000, distance_to_beach_m=2_000)

    ranked = ranked_hotels([far, near])

    assert [r.option.hotel.id for r in ranked] == ["near", "far"]
    assert any("пляжа" in note for note in explain(ranked, "far").cons)
    assert any("пляжа" in note for note in explain(ranked, "near").pros)


def test_pricier_hotel_is_told_how_much_more_it_costs() -> None:
    cheap = offer("cheap", 60_000)
    pricey = offer("pricey", 90_000)

    ranked = ranked_hotels([cheap, pricey])

    assert any(
        "дороже самого дешёвого" in note and "30" in note for note in explain(ranked, "pricey").cons
    )
    assert any("самый выгодный по цене" in note for note in explain(ranked, "cheap").pros)


def test_with_children_a_kids_club_and_pool_are_expected_even_if_not_requested() -> None:
    family = offer("family", 80_000, tags=[Tag.POOL, Tag.KIDS_CLUB])
    plain = offer("plain", 80_000, tags=[])
    request = make_request()
    request.party.children_ages.append(6)

    ranked = ranked_hotels([plain, family], request)

    assert ranked[0].option.hotel.id == "family"
    assert any("детский клуб" in note for note in explain(ranked, "family").pros)
    assert any("нет:" in note and "бассейн" in note for note in explain(ranked, "plain").cons)


def test_without_children_amenities_are_not_demanded() -> None:
    plain = offer("plain", 80_000, tags=[])

    ranked = ranked_hotels([plain])

    assert not explain(ranked, "plain").cons


def test_non_refundable_rate_is_flagged_as_a_risk_and_flexible_one_as_an_advantage() -> None:
    flexible = make_hotel_offer(
        hotel=make_hotel(id="a", name="a"), free_until=CHECK_IN - timedelta(days=7)
    )
    saver = make_hotel_offer(hotel=make_hotel(id="b", name="b"), free_until=None, rate_id="saver")

    ranked = ranked_hotels([flexible, saver])

    assert any("бесплатная отмена до 7 ноября" in note for note in explain(ranked, "a").pros)
    assert any("невозвратный" in note for note in explain(ranked, "b").risks)


def test_free_cancellation_that_is_about_to_expire_is_a_risk() -> None:
    soon = make_hotel_offer(free_until=TODAY + timedelta(days=1))

    explanation = ranked_hotels([soon])[0].explanation()

    assert any("совсем скоро" in note for note in explanation.risks)


def test_wanted_meal_plan_is_rewarded_and_a_lesser_one_is_called_out() -> None:
    all_inclusive = make_hotel_offer(meal_plan=MealPlan.AI, hotel=make_hotel(id="ai", name="ai"))
    breakfast = make_hotel_offer(
        meal_plan=MealPlan.BB, hotel=make_hotel(id="bb", name="bb"), rate_id="bb"
    )

    ranked = ranked_hotels([breakfast, all_inclusive], make_request(meal_plan=MealPlan.AI))

    assert ranked[0].option.hotel.id == "ai"
    assert any("питание как вы хотели" in note for note in explain(ranked, "ai").pros)
    assert any("а вы хотели" in note for note in explain(ranked, "bb").cons)


def test_budget_style_shifts_the_balance_between_price_and_quality() -> None:
    cheap = offer("cheap", 50_000, rating=7.6, distance_to_beach_m=600)
    nice = offer("nice", 100_000, rating=9.2, distance_to_beach_m=100)

    def advantage_of_nice(style: BudgetStyle) -> float:
        ranked = ranked_hotels([cheap, nice], make_request(budget_style=style))
        scores = {r.option.hotel.id: r.score for r in ranked}
        return scores["nice"] - scores["cheap"]

    economy, standard, premium = (
        advantage_of_nice(style)
        for style in (BudgetStyle.ECONOMY, BudgetStyle.STANDARD, BudgetStyle.PREMIUM)
    )

    assert economy < standard < premium
    assert economy < 0 < premium, "эконом выбирает дешёвый, премиум — лучший"


class TestScreening:
    def test_pets_remove_hotels_that_do_not_accept_them(self) -> None:
        request = make_request()
        request.party.pets.append("dog")
        friendly = offer("friendly", 80_000, pets_allowed=True)
        strict = offer("strict", 70_000, pets_allowed=False)

        screened = screen_hotels([strict, friendly], request)

        assert screened.kept == [friendly]
        assert screened.reasons == {"не принимает животных": 1}

    def test_min_stars_and_budget_are_hard_limits(self) -> None:
        request = make_request(min_stars=4, budget_total_rub=100_000)
        good = offer("good", 90_000, stars=4)
        three_stars = offer("three", 60_000, stars=3)
        too_pricey = offer("pricey", 130_000, stars=5)

        screened = screen_hotels([three_stars, good, too_pricey], request)

        assert screened.kept == [good]
        assert set(screened.reasons) == {"меньше 4★", "дороже всего бюджета"}
