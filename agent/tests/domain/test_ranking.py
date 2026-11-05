from odin.domain.ranking import Criterion, Ranked, Verdict, rank, reject_when, screen
from odin.domain.request import BudgetStyle
from odin.domain.scoring.common import PriceScale, price_verdict


def test_rank_orders_by_weighted_score_and_collects_explanations() -> None:
    criteria = [
        Criterion[int]("size", 1.0, lambda n: Verdict(n / 10, pro="крупный" if n >= 8 else None)),
        Criterion[int](
            "odd",
            3.0,
            lambda n: Verdict(1.0 if n % 2 else 0.0, con="чётный" if n % 2 == 0 else None),
        ),
    ]

    ranked = rank([8, 3, 9], criteria)

    assert [r.option for r in ranked] == [9, 3, 8]
    nine, three, eight = ranked
    assert nine.pros == ("крупный",)
    assert nine.cons == ()
    assert eight.cons == ("чётный",)
    assert three.score < nine.score
    assert 0 <= eight.score <= 1


def test_equal_scores_keep_input_order() -> None:
    criteria = [Criterion[str]("flat", 1.0, lambda _: Verdict(0.5))]

    assert [r.option for r in rank(["б", "а", "в"], criteria)] == ["б", "а", "в"]


def test_ranked_explanation_rounds_score_and_copies_notes() -> None:
    ranked = Ranked(option="x", score=0.8349, pros=("p",), cons=("c",), risks=("r",))

    explanation = ranked.explanation()

    assert (explanation.score, explanation.pros, explanation.cons, explanation.risks) == (
        0.83,
        ["p"],
        ["c"],
        ["r"],
    )


def test_screen_reports_first_failed_rule_and_counts_reasons() -> None:
    too_small = reject_when("слишком мало", lambda n: n < 3)
    even = reject_when("чётное", lambda n: n % 2 == 0)

    screened = screen([1, 2, 3, 4, 5], [too_small, even])

    assert screened.kept == [3, 5]
    assert [(d.option, d.reason) for d in screened.dropped] == [
        (1, "слишком мало"),
        (2, "слишком мало"),
        (4, "чётное"),
    ]
    assert screened.reasons == {"слишком мало": 2, "чётное": 1}


class TestPriceScale:
    prices = (20_000, 30_000, 40_000, 60_000, 100_000)

    def score(self, price: int, style: BudgetStyle) -> float:
        scale = PriceScale.of(list(self.prices))
        return price_verdict(price, scale, "дёшево", style).score

    def test_typical_price_is_in_the_middle_whatever_the_style(self) -> None:
        for style in BudgetStyle:
            assert self.score(40_000, style) == 0.5

    def test_cheaper_is_better_and_expensive_is_worse(self) -> None:
        for style in BudgetStyle:
            assert (
                self.score(20_000, style) > self.score(40_000, style) > self.score(100_000, style)
            )

    def test_economy_punishes_overpaying_harder_than_premium(self) -> None:
        assert self.score(100_000, BudgetStyle.ECONOMY) < self.score(100_000, BudgetStyle.STANDARD)
        assert self.score(100_000, BudgetStyle.STANDARD) < self.score(100_000, BudgetStyle.PREMIUM)

    def test_one_extreme_outlier_does_not_distort_the_scale(self) -> None:
        with_outlier = PriceScale.of([30_000, 32_000, 35_000, 38_000, 900_000])

        assert with_outlier.typical == 35_000

    def test_floor_makes_small_differences_negligible(self) -> None:
        scale = PriceScale.of([300, 1_500, 1_800])

        def gap(floor: int) -> float:
            cheap = price_verdict(300, scale, "x", BudgetStyle.STANDARD, floor=floor)
            pricey = price_verdict(1_800, scale, "x", BudgetStyle.STANDARD, floor=floor)
            return cheap.score - pricey.score

        assert gap(floor=3_000) < gap(floor=0) / 2

    def test_notes_name_the_cheapest_and_the_overpayment(self) -> None:
        scale = PriceScale.of(list(self.prices))

        cheapest = price_verdict(20_000, scale, "самый дешёвый", BudgetStyle.STANDARD)
        pricey = price_verdict(60_000, scale, "самый дешёвый", BudgetStyle.STANDARD)
        slightly_more = price_verdict(20_500, scale, "самый дешёвый", BudgetStyle.STANDARD)

        assert cheapest.pro == "самый дешёвый"
        assert pricey.con is not None
        assert "40" in pricey.con
        assert slightly_more.con is None, "разница меньше 10% не стоит упоминания"
