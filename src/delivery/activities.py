"""Activities: the non-deterministic work a Workflow delegates to the Worker.

`charge_payment` charges the order; `send_to_restaurant` creates its ticket. Both
calls are idempotent on the order id, so a retry after a crash never double-acts
(no double charge, no duplicate ticket). Dispatch and delivery Activities arrive
with later PRs.
"""

import httpx
from temporalio import activity

from delivery.models import Order
from delivery.shared import PAYMENT_URL, RESTAURANT_URL


@activity.defn
async def charge_payment(order: Order) -> str:
    async with httpx.AsyncClient(base_url=PAYMENT_URL, timeout=5.0) as client:
        response = await client.post(
            "/charge",
            json={"order_id": order.order_id, "amount_cents": order.amount_cents},
        )
        response.raise_for_status()
        return response.json()["charge_id"]


@activity.defn
async def send_to_restaurant(order: Order) -> str:
    async with httpx.AsyncClient(base_url=RESTAURANT_URL, timeout=5.0) as client:
        response = await client.post(
            "/tickets",
            json={"order_id": order.order_id, "description": order.description},
        )
        response.raise_for_status()
        return response.json()["ticket_id"]
