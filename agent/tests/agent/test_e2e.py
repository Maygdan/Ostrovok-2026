"""Сквозные сценарии на моках и демо-заглушке: от первого сообщения до имитации оплаты."""

from datetime import timedelta

from odin.domain.plan import Severity
from tests.agent.helpers import Conversation

HEADLINE = "Хочу к тёплому морю в сентябре, недорого, с ребёнком, без долгих перелётов"


async def test_one_message_to_a_simulated_purchase_with_a_replan(
    conversation: Conversation,
) -> None:
    session = conversation.session

    # 1. Одно сообщение своими словами: агент достаёт явные и скрытые требования
    #    и сразу предлагает направления, не устраивая анкету.
    reply = await conversation.say(HEADLINE)

    request = session.request
    assert (request.month, request.max_travel_hours) == (9, 5)
    assert request.party.children_ages == [7]
    assert (request.min_sea_temp_c, request.budget_style.value) == (22, "economy")
    assert "Допущения" in reply, "допущения названы, а не спрятаны"
    assert "Не подошли:" in reply, "сказано, что отброшено и почему"
    assert conversation.tools_used == ["update_trip_request", "search_destinations"]
    assert session.plan is None

    # 2. Пользователь выбирает направление — собирается целый план с объяснениями.
    reply = await conversation.say("Давай первый вариант")

    first = session.plan
    assert first is not None
    assert conversation.tools_used == ["update_trip_request", "build_plan"]
    assert first.missing_slots == []
    assert first.errors == []
    assert all(first.explanations[slot].pros for slot in first.explanations)
    assert "Почему подходит" in reply
    assert "Чем пожертвовали" in reply
    assert "Стыковки проверены" in reply or "Проверка стыковок" in reply

    # 3. Условия меняются — план пересобирается, а не ищется с нуля.
    reply = await conversation.say("А можно на два дня позже?")

    second = session.plan
    assert second is not None
    assert conversation.tools_used == ["update_trip_request", "build_plan"]
    assert second.destination.id == first.destination.id
    assert second.check_in == first.check_in + timedelta(days=2)
    assert second.hotel.id == first.hotel.id, "отель и тариф те же"
    assert second.outbound.id == first.outbound.id, "тот же рейс, но на новую дату"
    assert second.revision == first.revision + 1
    assert second.errors == []
    assert "Что изменилось" in reply
    assert "тот же вариант на новые даты" in reply

    # 4. Корзина: показывается пользователю, оплата ждёт подтверждения.
    reply = await conversation.say("Оформляй")

    assert conversation.tools_used == ["create_cart"]
    cart = session.cart
    assert cart is not None
    assert cart.total_price_rub == second.total_price_rub
    assert cart.presented
    assert session.order is None
    assert "Подтверждаете оплату" in reply

    # 5. Подтверждение — имитация оплаты и коды подтверждения по каждой позиции.
    reply = await conversation.say("Оплачиваю")

    order = session.order
    assert order is not None
    assert conversation.tools_used == ["pay_cart"]
    assert order.total_price_rub == second.total_price_rub
    assert len(order.bookings) == 5
    assert session.cart.status.value == "paid"
    assert all(booking.confirmation_code in reply for booking in order.bookings)
    assert "имитация" in reply


async def test_a_dog_and_a_smaller_budget_replan_only_what_they_touch(
    conversation: Conversation,
) -> None:
    session = conversation.session
    await conversation.say(HEADLINE)
    await conversation.say("первый")
    original = session.plan

    await conversation.say("С нами будет собака")
    with_dog = session.plan

    assert with_dog.hotel.hotel.pets_allowed
    assert with_dog.outbound.pets_allowed
    assert with_dog.inbound.pets_allowed
    assert with_dog.errors == []
    assert with_dog.check_in == original.check_in, "даты не тронуты"

    await conversation.say("Бюджет меньше")
    cheaper = session.plan

    budget = session.request.budget_total_rub
    assert budget is not None
    assert budget < with_dog.total_price_rub
    assert cheaper.total_price_rub <= budget
    assert cheaper.hotel.hotel.pets_allowed, "ограничение по питомцу сохранилось"
    assert [i for i in cheaper.issues if i.severity is Severity.ERROR] == []


async def test_changing_the_plan_after_the_cart_invalidates_the_cart(
    conversation: Conversation,
) -> None:
    session = conversation.session
    for phrase in (HEADLINE, "первый", "Оформляй"):
        await conversation.say(phrase)
    old_cart = session.cart
    old_revision = session.plan.revision

    await conversation.say("Давай на день позже")

    assert session.cart is None, "корзина от прежнего плана больше не верна"
    assert session.plan.revision == old_revision + 1

    await conversation.say("Оформляй")
    new_cart = session.cart

    assert new_cart is not None
    assert new_cart.id != old_cart.id
    assert new_cart.plan_revision == session.plan.revision

    await conversation.say("Оплачиваю")
    assert session.order is not None


async def test_restating_the_request_before_choosing_re_runs_the_search(
    conversation: Conversation,
) -> None:
    session = conversation.session
    await conversation.say(HEADLINE)

    reply = await conversation.say("А если подешевле?")

    assert conversation.tools_used == ["update_trip_request", "search_destinations"]
    assert session.plan is None
    assert "Подходящие направления" in reply or "ничего не подошло" in reply


async def test_an_unknown_named_destination_is_not_replaced_with_a_suggestion(
    conversation: Conversation,
) -> None:
    reply = await conversation.say("Хочу в хабаровск в августе")

    assert "хабаровск" in reply.lower()
    assert "Сочи" not in reply
    assert "подменять город не буду" in reply
    assert conversation.tools_used == []


async def test_generic_trip_ideas_are_not_mistaken_for_unknown_cities(
    conversation: Conversation,
) -> None:
    reply = await conversation.say("На выходные в красивый город в ноябре")

    assert "Подходящие направления" in reply
    assert conversation.tools_used == ["update_trip_request", "search_destinations"]
