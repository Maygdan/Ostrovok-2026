from dataclasses import replace

import pytest

from odin.domain.errors import DomainError
from odin.domain.order import CartStatus
from odin.domain.plan import Slot
from odin.providers.mock import build_mock_providers
from odin.services.checkout import CheckoutService
from tests.factories import make_hotel_offer, make_plan, make_request


class SpyPayments:
    """Запоминает, по каким ключам и какие квитанции вернул платёжный провайдер."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.keys: list[str] = []
        self.receipts: list = []

    async def charge(self, amount_rub, description, method, idempotency_key):
        self.keys.append(idempotency_key)
        receipt = await self._inner.charge(amount_rub, description, method, idempotency_key)
        self.receipts.append(receipt)
        return receipt


@pytest.fixture
def checkout() -> CheckoutService:
    return CheckoutService(build_mock_providers())


class TestCart:
    def test_every_part_of_the_plan_becomes_an_item_with_its_terms(
        self, checkout: CheckoutService
    ) -> None:
        plan = make_plan()

        cart = checkout.create_cart(plan)

        assert [item.slot for item in cart.items] == list(Slot)
        assert cart.total_price_rub == plan.total_price_rub
        assert cart.plan_revision == plan.revision
        assert cart.status is CartStatus.OPEN
        assert not cart.presented
        hotel_item = next(item for item in cart.items if item.slot is Slot.HOTEL)
        assert hotel_item.offer_id == plan.hotel.id
        assert hotel_item.conditions == "бесплатная отмена до 7 ноября"
        flight_item = next(item for item in cart.items if item.slot is Slot.OUTBOUND)
        assert "невозвратный тариф" in flight_item.conditions

    def test_non_refundable_hotel_is_labelled_in_the_cart(self, checkout: CheckoutService) -> None:
        plan = make_plan(hotel=make_hotel_offer(free_until=None))

        cart = checkout.create_cart(plan)

        hotel_item = next(item for item in cart.items if item.slot is Slot.HOTEL)
        assert hotel_item.conditions == "невозвратный тариф"

    def test_incomplete_plan_is_not_checked_out(self, checkout: CheckoutService) -> None:
        with pytest.raises(DomainError, match="не хватает: дорога обратно"):
            checkout.create_cart(make_plan(inbound=None))

    def test_plan_with_blocking_problems_is_not_checked_out(
        self, checkout: CheckoutService
    ) -> None:
        over_budget = make_plan(built_for=make_request(budget_total_rub=100_000))

        with pytest.raises(DomainError, match="бюджета"):
            checkout.create_cart(over_budget)


class TestPayment:
    async def test_paying_a_presented_cart_confirms_every_item(
        self, checkout: CheckoutService
    ) -> None:
        plan = make_plan()
        cart = checkout.create_cart(plan).mark_presented()

        order = await checkout.pay(cart, plan)

        assert order.total_price_rub == plan.total_price_rub
        assert order.receipt.amount_rub == plan.total_price_rub
        assert order.cart_id == cart.id
        assert [b.slot for b in order.bookings] == [item.slot for item in cart.items]
        codes = [b.confirmation_code for b in order.bookings]
        assert len(set(codes)) == len(codes)

    async def test_cart_never_shown_to_the_user_cannot_be_paid(
        self, checkout: CheckoutService
    ) -> None:
        plan = make_plan()
        cart = checkout.create_cart(plan)

        with pytest.raises(DomainError, match="не видел пользователь"):
            await checkout.pay(cart, plan)

    async def test_cart_of_an_outdated_plan_cannot_be_paid(self, checkout: CheckoutService) -> None:
        plan = make_plan()
        cart = checkout.create_cart(plan).mark_presented()
        newer = plan.model_copy(update={"revision": plan.revision + 1})

        with pytest.raises(DomainError, match="оформите корзину заново"):
            await checkout.pay(cart, newer)

    async def test_cart_cannot_be_paid_once_the_plan_has_blocking_problems(
        self, checkout: CheckoutService
    ) -> None:
        plan = make_plan()
        cart = checkout.create_cart(plan).mark_presented()
        over_budget = plan.model_copy(update={"built_for": make_request(budget_total_rub=1_000)})

        with pytest.raises(DomainError, match="бюджета"):
            await checkout.pay(cart, over_budget)

    async def test_retrying_after_a_booking_failure_does_not_charge_twice(self) -> None:
        providers = build_mock_providers()
        payments = SpyPayments(providers.payments)
        failures: list[Exception | None] = [RuntimeError("поставщик недоступен"), None]

        class FlakyBookings:
            async def book(self, items, order_id):
                if failure := failures.pop(0):
                    raise failure
                return await providers.bookings.book(items, order_id)

        checkout = CheckoutService(replace(providers, payments=payments, bookings=FlakyBookings()))
        plan = make_plan()
        cart = checkout.create_cart(plan).mark_presented()

        with pytest.raises(RuntimeError):
            await checkout.pay(cart, plan)
        order = await checkout.pay(cart, plan)

        assert payments.keys == [cart.id, cart.id], "обе попытки списывают по одному ключу"
        assert payments.receipts[0] == payments.receipts[1], "провайдер не списал деньги дважды"
        assert order.receipt == payments.receipts[1]
        assert order.id == f"ORD-{cart.id.removeprefix('cart-').upper()}"

    async def test_paid_cart_cannot_be_paid_twice(self, checkout: CheckoutService) -> None:
        plan = make_plan()
        cart = checkout.create_cart(plan).mark_presented()
        await checkout.pay(cart, plan)

        with pytest.raises(DomainError, match="уже оплачена"):
            await checkout.pay(cart.mark_paid(), plan)

    def test_cart_transitions_do_not_mutate_the_original(self, checkout: CheckoutService) -> None:
        cart = checkout.create_cart(make_plan())

        presented = cart.mark_presented()

        assert presented.presented
        assert not cart.presented
        assert presented.mark_paid().status is CartStatus.PAID
