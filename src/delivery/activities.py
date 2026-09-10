"""Activities: the non-deterministic work a Workflow delegates to the Worker.

`charge_payment` charges the order, `send_to_restaurant` creates its ticket, and
`dispatch_driver` assigns a driver. Each call is idempotent on the order id, so a
retry after a crash never double-acts (no double charge, duplicate ticket, or
second driver). The delivery Activity arrives with a later PR.
"""

import httpx
from temporalio import activity

from delivery.models import Order
from delivery.shared import DISPATCH_URL, PAYMENT_URL, RESTAURANT_URL


@activity.defn
async def charge_payment(order: Order) -> str:
    activity.logger.info(f"[charge]     order {order.order_id}: calling the payment service")
    async with httpx.AsyncClient(base_url=PAYMENT_URL, timeout=5.0) as client:
        response = await client.post(
            "/charge",
            json={"order_id": order.order_id, "amount_cents": order.amount_cents},
        )
        response.raise_for_status()
        charge_id = response.json()["charge_id"]
        activity.logger.info(f"[charge]     order {order.order_id}: charged ({charge_id})")
        return charge_id


@activity.defn
async def send_to_restaurant(order: Order) -> str:
    activity.logger.info(f"[restaurant] order {order.order_id}: calling the restaurant service")
    async with httpx.AsyncClient(base_url=RESTAURANT_URL, timeout=5.0) as client:
        response = await client.post(
            "/tickets",
            json={"order_id": order.order_id, "description": order.description},
        )
        response.raise_for_status()
        ticket_id = response.json()["ticket_id"]
        activity.logger.info(f"[restaurant] order {order.order_id}: ticket created ({ticket_id})")
        return ticket_id


@activity.defn
async def dispatch_driver(order: Order) -> str:
    activity.logger.info(f"[dispatch]   order {order.order_id}: calling the dispatch service")
    async with httpx.AsyncClient(base_url=DISPATCH_URL, timeout=5.0) as client:
        response = await client.post(
            "/dispatches",
            json={"order_id": order.order_id},
        )
        response.raise_for_status()
        dispatch_id = response.json()["dispatch_id"]
        activity.logger.info(f"[dispatch]   order {order.order_id}: driver dispatched ({dispatch_id})")
        return dispatch_id
