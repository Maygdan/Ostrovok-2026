"""Имитация оплаты и подтверждения брони. Деньги не списываются, поставщики не вызываются."""

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

from odin.domain.order import Booking, CartItem, PaymentReceipt


class MockPayments:
    def __init__(self) -> None:
        self._receipts: dict[str, PaymentReceipt] = {}

    async def charge(
        self, amount_rub: int, description: str, method: str, idempotency_key: str
    ) -> PaymentReceipt:
        if idempotency_key not in self._receipts:
            self._receipts[idempotency_key] = PaymentReceipt(
                transaction_id=f"pay_{uuid4().hex[:12]}",
                amount_rub=amount_rub,
                method=method,
                paid_at=datetime.now(UTC),
            )
        return self._receipts[idempotency_key]


class MockBookings:
    async def book(self, items: Sequence[CartItem], order_id: str) -> list[Booking]:
        return [
            Booking(
                slot=item.slot,
                offer_id=item.offer_id,
                title=item.title,
                confirmation_code=_confirmation_code(order_id, item),
            )
            for item in items
        ]


def _confirmation_code(order_id: str, item: CartItem) -> str:
    """Стабильный псевдокод подтверждения: один и тот же заказ даёт те же коды.

    В хеш входит слот: id предложения уникален лишь внутри части плана (оба трансфера — «taxi»).
    """
    return hashlib.sha1(f"{order_id}:{item.slot}:{item.offer_id}".encode()).hexdigest()[:6].upper()
