"""Корзина, оплата и заказ."""

from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, computed_field

from odin.domain.plan import Slot


class CartStatus(StrEnum):
    OPEN = "open"
    PAID = "paid"


class CartItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    slot: Slot
    offer_id: str
    title: str
    price_rub: int
    conditions: str = Field(description="Условия отмены и важные оговорки одной строкой")


class Cart(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    items: list[CartItem]
    plan_revision: int = Field(description="Ревизия плана, по которому собрана корзина")
    presented: bool = Field(False, description="Корзину уже показали пользователю")
    status: CartStatus = CartStatus.OPEN

    @computed_field
    @property
    def total_price_rub(self) -> int:
        return sum(item.price_rub for item in self.items)

    def mark_presented(self) -> Self:
        return self.model_copy(update={"presented": True})

    def mark_paid(self) -> Self:
        return self.model_copy(update={"status": CartStatus.PAID})


class PaymentReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    transaction_id: str
    amount_rub: int
    method: str
    paid_at: AwareDatetime


class Booking(BaseModel):
    """Подтверждение поставщика по одной позиции заказа."""

    model_config = ConfigDict(frozen=True)

    slot: Slot
    offer_id: str
    title: str
    confirmation_code: str


class Order(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    cart_id: str
    total_price_rub: int
    receipt: PaymentReceipt
    bookings: list[Booking]
