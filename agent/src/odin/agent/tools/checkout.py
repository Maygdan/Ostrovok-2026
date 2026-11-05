"""Инструменты оформления: корзина и имитация оплаты."""

from typing import Any

from pydantic import Field

from odin.agent.tools.base import Tool, ToolArgs, ToolContext, ToolError
from odin.agent.tools.plan import NoArgs
from odin.agent.views import cart_view, order_view


class PayCartArgs(ToolArgs):
    confirmed: bool = Field(
        description="true — пользователь в отдельном сообщении явно подтвердил оплату корзины."
    )
    payment_method: str = Field("card", description="Способ оплаты (имитация).")


async def create_cart(ctx: ToolContext, args: NoArgs) -> dict[str, Any]:
    ctx.forbid_after_order()
    cart = ctx.checkout.create_cart(ctx.require_current_plan())
    ctx.session.cart = cart
    return {
        "cart": cart_view(cart),
        "next": (
            "Покажите корзину пользователю и спросите, подтверждает ли он оплату. "
            "Не вызывайте pay_cart в этом же сообщении."
        ),
        "summary": f"Корзина {cart.id} на {cart.total_price_rub} ₽ создана",
    }


async def pay_cart(ctx: ToolContext, args: PayCartArgs) -> dict[str, Any]:
    if not args.confirmed:
        raise ToolError(
            "Оплата возможна только после явного подтверждения пользователя (confirmed=true)."
        )
    ctx.forbid_after_order()
    session = ctx.session
    if session.cart is None:
        raise ToolError("Корзины нет: сначала вызовите create_cart.")
    order = await ctx.checkout.pay(session.cart, ctx.require_current_plan(), args.payment_method)
    session.cart = session.cart.mark_paid()
    session.order = order
    return {
        "order": order_view(order),
        "summary": f"Заказ {order.id} оплачен (имитация), итого {order.total_price_rub} ₽",
    }


TOOLS = [
    Tool(
        name="create_cart",
        description=(
            "Собрать корзину из актуального плана. Возможно только для полного плана без "
            "блокирующих проблем. После создания покажите корзину пользователю и спросите, "
            "подтверждает ли он оплату."
        ),
        arguments=NoArgs,
        handler=create_cart,
    ),
    Tool(
        name="pay_cart",
        description=(
            "Имитация оплаты корзины и подтверждение брони (деньги не списываются). Вызывайте "
            "ТОЛЬКО после того, как пользователь в отдельном сообщении явно подтвердил оплату, "
            "увидев корзину; confirmed=true означает именно такое подтверждение."
        ),
        arguments=PayCartArgs,
        handler=pay_cart,
    ),
]
