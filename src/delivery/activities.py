"""Activities: the non-deterministic work a Workflow delegates to the Worker.

`charge_payment` calls the payment service to charge an order. The call is
idempotent on the order id, so a retry after a crash never double-charges. PR 3
adds the restaurant, dispatch, and delivery Activities.
"""

import httpx
from temporalio import activity

from delivery.models import Order
from delivery.shared import PAYMENT_URL


@activity.defn
async def charge_payment(order: Order) -> str:
    async with httpx.AsyncClient(base_url=PAYMENT_URL, timeout=5.0) as client:
        response = await client.post(
            "/charge",
            json={"order_id": order.order_id, "amount_cents": order.amount_cents},
        )
        response.raise_for_status()
        return response.json()["charge_id"]
