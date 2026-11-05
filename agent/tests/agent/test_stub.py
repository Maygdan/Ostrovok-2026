import json
from typing import Any

import pytest

from odin.agent.llm.stub.dialogue import Dialogue
from odin.agent.llm.stub.understanding import understand, wants_cart, wants_payment
from odin.agent.llm.types import Message, ToolCall
from tests.agent.helpers import Conversation

HEADLINE = "Хочу к тёплому морю в сентябре, недорого, с ребёнком, без долгих перелётов"


class TestUnderstanding:
    def test_the_headline_request_is_decomposed_into_explicit_and_implied_requirements(
        self,
    ) -> None:
        patch = understand(HEADLINE)

        assert patch == {
            "month": 9,
            "children_ages": [7],
            "budget_style": "economy",
            "tags": ["beach"],
            "min_sea_temp_c": 22,
            "min_air_temp_c": 22,
            "max_travel_hours": 5,
            "assumptions": ["Возраст ребёнка не указан — принят 7 лет."],
        }

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("а можно на два дня позже?", {"shift_days": 2}),
            ("давай на 3 дня раньше", {"shift_days": -3}),
            ("давай на день позже", {"shift_days": 1}),
            ("перенесём позже на неделю", {"shift_days": 7}),
            ("сдвинь на 2 недели позже", {"shift_days": 14}),
            ("бюджет меньше", {"cheaper_by_percent": 10}),
            ("хочу подешевле, на 20%", {"cheaper_by_percent": 20}),
            ("с нами будет собака", {"pets": ["dog"]}),
            ("мы едем с котом", {"pets": ["cat"]}),
            (
                "Изменить поездку: с 2027-09-10, на 7 ночей, "
                "2 взрослых, 0 детей, бюджет до 120000 ₽",
                {
                    "date_from": "2027-09-10",
                    "nights": 7,
                    "adults": 2,
                    "children_ages": [],
                    "budget_total_rub": 120_000,
                },
            ),
            ("в декабре, бюджет до 150 тысяч", {"month": 12, "budget_total_rub": 150_000}),
            ("не больше 200 000 рублей", {"budget_total_rub": 200_000}),
            ("с двумя детьми 3 и 8 лет", {"children_ages": [3, 8]}),
            ("нас двое, едем вдвоём на 10 дней", {"adults": 2, "nights": 10}),
            ("хочу в горы покататься на лыжах", {"tags": ["ski", "mountains"]}),
            ("на выходные в Питер поездом", {"nights": 2, "transport_kinds": ["train"]}),
            (
                "с 2027-09-10, на 7 ночей, 2 взрослых, 1 детей, бюджет до 120000 ₽",
                {
                    "date_from": "2027-09-10",
                    "nights": 7,
                    "adults": 2,
                    "children_ages": [7],
                    "budget_total_rub": 120_000,
                },
            ),
            (
                "с 2027-09-10 по 2027-09-17, 2 взрослых, 0 детей",
                {
                    "date_from": "2027-09-10",
                    "nights": 7,
                    "adults": 2,
                    "children_ages": [],
                },
            ),
            ("нужен отель 5 звёзд всё включено", {"min_stars": 5, "meal_plan": "AI"}),
            ("до 3 часов лёту", {"max_travel_hours": 3}),
        ],
    )
    def test_typical_phrasings(self, text: str, expected: dict[str, Any]) -> None:
        patch = understand(text)
        patch.pop("assumptions", None)

        assert patch == expected

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("хочу без пересадок", {"max_stops": 0}),
            ("только прямые рейсы", {"max_stops": 0}),
            ("отель с бесплатной отменой", {"free_cancellation": True}),
            ("в ноябре, без долгих перелётов", {"max_travel_hours": 5}),
        ],
    )
    def test_nonstop_and_cancellation_wishes(self, text: str, expected: dict[str, Any]) -> None:
        found = understand(text)

        assert {key: found[key] for key in expected} == expected
        assert ("max_stops" in found) == ("max_stops" in expected), (
            "«без долгих» — не «без пересадок»"
        )

    def test_shifting_dates_is_not_mistaken_for_a_new_duration_or_month(self) -> None:
        assert understand("а можно на два дня позже?") == {"shift_days": 2}

    def test_relative_budget_wins_over_absolute_fields(self) -> None:
        patch = understand("подешевле, до 100 тысяч")

        assert "cheaper_by_percent" in patch
        assert "budget_total_rub" not in patch
        assert "budget_style" not in patch

    def test_one_child_is_not_a_solo_traveller(self) -> None:
        assert "adults" not in understand("у нас один ребёнок 5 лет")

    def test_unrelated_text_is_not_understood(self) -> None:
        assert understand("спасибо, пока") == {}

    def test_cart_and_payment_phrases(self) -> None:
        assert wants_cart("Оформляй")
        assert wants_cart("положи в корзину")
        assert wants_payment("Оплачиваю")
        assert wants_payment("да, подтверждаю")
        assert not wants_cart("давай подешевле")

    @pytest.mark.parametrize(
        "text",
        [
            "Оплачиваю",
            "Да, оплачиваю",
            "Подтверждаю оплату",
            "Оплатите, пожалуйста",
            "Хорошо, оплачивайте",
            "Готов оплатить",
        ],
    )
    def test_explicit_confirmation_is_payment(self, text: str) -> None:
        assert wants_payment(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Нет, не оплачивай, я подумаю",
            "Какие способы оплаты есть?",
            "А как оплатить?",
            "Подождите, оплатим позже",
            "А что если я не подтверждаю?",
            "Оплата — это точно безопасно?",
        ],
    )
    def test_refusals_doubts_and_questions_are_not_payment(self, text: str) -> None:
        assert not wants_payment(text)


def history_with_options() -> list[Message]:
    options = {
        "options": [
            {"id": "anapa", "name": "Анапа"},
            {"id": "sochi", "name": "Сочи"},
            {"id": "kaliningrad", "name": "Калининград"},
        ]
    }
    call = ToolCall.of("search_destinations")
    return [
        Message.user(HEADLINE),
        Message.assistant("", [call]),
        Message.tool_result(call.id, json.dumps(options, ensure_ascii=False)),
        Message.assistant("Вот варианты"),
    ]


class TestChoosingFromTheOfferedList:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Давай первый вариант", "anapa"),
            ("второй", "sochi"),
            ("вариант 3", "kaliningrad"),
            ("2", "sochi"),
            ("Хочу в Сочи", "sochi"),
            ("поехали в Калининград!", "kaliningrad"),
            ("а в Анапе что с погодой?", "anapa"),
        ],
    )
    def test_by_ordinal_number_or_name(self, text: str, expected: str) -> None:
        dialogue = Dialogue([*history_with_options(), Message.user(text)])

        assert dialogue.chosen_destination() == expected

    @pytest.mark.parametrize("text", ["на 3 дня", "бюджет 100000", "что-то другое", "пятый"])
    def test_other_messages_do_not_choose_anything(self, text: str) -> None:
        dialogue = Dialogue([*history_with_options(), Message.user(text)])

        assert dialogue.chosen_destination() is None

    def test_nothing_to_choose_before_any_search(self) -> None:
        assert Dialogue([Message.user("первый")]).chosen_destination() is None


class TestBehaviour:
    async def test_help_and_unknown_messages_are_answered_without_tools(
        self, conversation: Conversation
    ) -> None:
        help_text = await conversation.say("помощь")
        unknown = await conversation.say("ыыы")

        assert "демо-режим" in help_text.lower()
        assert "LLM_API_KEY" in help_text
        assert "не разобрал" in unknown
        assert conversation.steps == []

    async def test_first_message_searches_destinations_and_states_assumptions(
        self, conversation: Conversation
    ) -> None:
        reply = await conversation.say(HEADLINE)

        assert conversation.tools_used == ["update_trip_request", "search_destinations"]
        assert "Допущения" in reply
        assert "Вылет из города Москва" in reply
        assert "Возраст ребёнка не указан" in reply
        assert "Не подошли:" in reply
        assert "Какое направление берём" in reply

    async def test_payment_phrase_before_a_plan_is_not_a_payment(
        self, conversation: Conversation
    ) -> None:
        reply = await conversation.say("Оплачиваю")

        assert "pay_cart" not in conversation.tools_used
        assert "не разобрал" in reply

    async def test_pay_phrase_with_plan_but_no_cart_creates_the_cart_first(
        self, conversation: Conversation
    ) -> None:
        await conversation.say(HEADLINE)
        await conversation.say("первый")

        reply = await conversation.say("Оплачиваю")

        assert conversation.tools_used == ["create_cart"]
        assert conversation.session.order is None
        assert "Подтверждаете оплату" in reply

    async def test_wishes_for_nonstop_and_free_cancellation_reach_the_plan_and_the_recap(
        self, conversation: Conversation
    ) -> None:
        reply = await conversation.say(f"{HEADLINE}, без пересадок и с бесплатной отменой")

        assert "без пересадок" in reply
        assert "с бесплатной отменой отеля" in reply
        request = conversation.session.request
        assert (request.max_stops, request.free_cancellation) == (0, True)

        await conversation.say("первый")
        plan = conversation.session.plan
        assert plan.outbound.stops == plan.inbound.stops == 0
        assert plan.hotel.cancellation.refundable

    async def test_naming_the_duration_later_removes_only_the_assumption_about_it(
        self, conversation: Conversation
    ) -> None:
        await conversation.say(HEADLINE)
        await conversation.say("первый")
        before = list(conversation.session.request.assumptions)
        assert any("7 ночей" in note for note in before)

        await conversation.say("а можно на 10 ночей?")

        after = conversation.session.request.assumptions
        assert not any("7 ночей" in note for note in after)
        assert [note for note in before if "7 ночей" not in note] == after

    async def test_a_question_or_refusal_with_an_open_cart_does_not_pay(
        self, conversation: Conversation
    ) -> None:
        for phrase in (HEADLINE, "первый", "Оформляй"):
            await conversation.say(phrase)

        for phrase in ("Какие способы оплаты есть?", "Нет, не оплачивай, я подумаю"):
            await conversation.say(phrase)
            assert "pay_cart" not in conversation.tools_used, phrase
            assert conversation.session.order is None

        await conversation.say("Оплачиваю")
        assert conversation.tools_used == ["pay_cart"]
        assert conversation.session.order is not None

    async def test_after_the_purchase_changes_are_refused(self, conversation: Conversation) -> None:
        for phrase in (HEADLINE, "первый", "Оформляй", "Оплачиваю"):
            await conversation.say(phrase)

        reply = await conversation.say("а можно на два дня позже?")

        assert "Заказ уже оформлен" in reply
        assert conversation.steps == []
