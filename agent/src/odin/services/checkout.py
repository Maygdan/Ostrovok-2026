"""Корзина и оформление заказа с имитацией оплаты."""

from uuid import uuid4

from odin.domain.errors import DomainError
from odin.domain.formatting import day_month
from odin.domain.hotel import HotelOffer
from odin.domain.junctions import check_plan
from odin.domain.order import Cart, CartItem, CartStatus, Order
from odin.domain.plan import SLOT_LABELS, Offer, Severity, Slot, TripPlan
from odin.domain.transport import TransportOffer
from odin.providers.interfaces import Providers


class CheckoutService:
    def __init__(self, providers: Providers) -> None:
        self._providers = providers

    def create_cart(self, plan: TripPlan) -> Cart:
        """Складывает план в корзину. Неполный план или план с ошибками не оформляется."""
        _require_orderable(plan)
        items = [_cart_item(slot, offer) for slot in Slot if (offer := plan.get(slot)) is not None]
        return Cart(id=f"cart-{uuid4().hex[:8]}", items=items, plan_revision=plan.revision)

    async def pay(self, cart: Cart, plan: TripPlan, method: str = "card") -> Order:
        """Имитирует оплату. Деньги не списываются; заказ подтверждается во всех позициях."""
        if cart.status is CartStatus.PAID:
            raise DomainError("Корзина уже оплачена.")
        if not cart.presented:
            raise DomainError(
                "Корзину ещё не видел пользователь. Покажите её и оплачивайте только после "
                "его явного подтверждения в отдельном сообщении."
            )
        if cart.plan_revision != plan.revision:
            raise DomainError("План изменился после создания корзины: оформите корзину заново.")
        _require_orderable(plan)
        order_id = f"ORD-{cart.id.removeprefix('cart-').upper()}"  # повтор оплаты не плодит заказы
        description = f"Поездка: {plan.destination.name}, {day_month(plan.check_in)}"
        receipt = await self._providers.payments.charge(
            cart.total_price_rub, description, method, idempotency_key=cart.id
        )
        bookings = await self._providers.bookings.book(cart.items, order_id)
        return Order(
            id=order_id,
            cart_id=cart.id,
            total_price_rub=cart.total_price_rub,
            receipt=receipt,
            bookings=bookings,
        )


def _require_orderable(plan: TripPlan) -> None:
    """План можно оформлять и оплачивать, только если он полный и без блокирующих проблем."""
    if plan.missing_slots:
        missing = ", ".join(SLOT_LABELS[slot].lower() for slot in plan.missing_slots)
        raise DomainError(f"План неполный, не хватает: {missing}.")
    errors = [issue for issue in check_plan(plan) if issue.severity is Severity.ERROR]
    if errors:
        problems = " ".join(issue.message for issue in errors)
        raise DomainError(f"В плане есть проблемы, которые нужно решить до оформления: {problems}")


def _cart_item(slot: Slot, offer: Offer) -> CartItem:
    return CartItem(
        slot=slot,
        offer_id=offer.id,
        title=offer.title,
        price_rub=offer.total_price_rub,
        conditions=_conditions(offer),
    )


def _conditions(offer: Offer) -> str:
    if isinstance(offer, HotelOffer):
        until = offer.cancellation.free_until
        return f"бесплатная отмена до {day_month(until)}" if until else "невозвратный тариф"
    if isinstance(offer, TransportOffer):
        fare = "возвратный тариф" if offer.refundable else "невозвратный тариф"
        baggage = "багаж включён" if offer.baggage_included else "багаж не включён"
        return f"{fare}, {baggage}"
    return ""
