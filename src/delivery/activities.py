"""Activities: the non-deterministic work a Workflow delegates to the Worker.

`charge_payment` charges the order, `send_to_restaurant` creates its ticket, and
`dispatch_driver` assigns a driver. Each call is idempotent on the order id, so a
retry after a crash never double-acts (no double charge, duplicate ticket, or
second driver). The delivery Activity arrives with a later PR.
"""

import httpx
from temporalio import activity
from temporalio.exceptions import ApplicationError

from delivery.models import Order
from delivery.shared import DISPATCH_URL, PAYMENT_URL, RESTAURANT_URL


class DeliveryActivities:
    """The three service calls, sharing one way of reaching the services.

    The Worker creates this with no arguments, so each call goes over the network.
    Tests pass an httpx transport instead, which lets them run the Activities
    against the real stub apps in memory, or against a transport that fails on
    purpose.
    """

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def _client(self, base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=base_url, timeout=5.0, transport=self._transport)

    async def _post(self, service: str, base_url: str, path: str, body: dict) -> dict:
        """POST to a service and return its JSON reply.

        A failure becomes a short ApplicationError naming the service and the
        reason. `from None` drops httpx's cause chain, which Temporal would
        otherwise record in full, past its failure size limit, leaving the Web UI
        to show "Failure exceeds size limit." in place of the reason. An
        unreachable service, a timeout or a server error may clear up, so those
        stay retryable. A 4xx means this Activity sent a bad request, which
        retrying can't fix, so that one is non-retryable.
        """
        try:
            async with self._client(base_url) as client:
                response = await client.post(path, json=body)
        except httpx.TimeoutException:
            raise ApplicationError(f"{service} service timed out") from None
        except httpx.TransportError as err:
            raise ApplicationError(f"{service} service unreachable: {err}") from None

        if response.is_client_error:
            raise ApplicationError(
                f"{service} service rejected the request: {response.status_code}",
                non_retryable=True,
            ) from None
        if response.is_error:
            raise ApplicationError(f"{service} service returned {response.status_code}") from None

        return response.json()

    @activity.defn
    async def charge_payment(self, order: Order) -> str:
        activity.logger.info(f"[charge]     order {order.order_id}: calling the payment service")
        reply = await self._post(
            "payment",
            PAYMENT_URL,
            "/charge",
            {"order_id": order.order_id, "amount_cents": order.amount_cents},
        )
        charge_id = reply["charge_id"]
        activity.logger.info(f"[charge]     order {order.order_id}: charged ({charge_id})")
        return charge_id

    @activity.defn
    async def send_to_restaurant(self, order: Order) -> str:
        activity.logger.info(f"[restaurant] order {order.order_id}: calling the restaurant service")
        reply = await self._post(
            "restaurant",
            RESTAURANT_URL,
            "/tickets",
            {"order_id": order.order_id, "description": order.description},
        )
        ticket_id = reply["ticket_id"]
        activity.logger.info(f"[restaurant] order {order.order_id}: ticket created ({ticket_id})")
        return ticket_id

    @activity.defn
    async def dispatch_driver(self, order: Order) -> str:
        activity.logger.info(f"[dispatch]   order {order.order_id}: calling the dispatch service")
        reply = await self._post(
            "dispatch",
            DISPATCH_URL,
            "/dispatches",
            {"order_id": order.order_id},
        )
        dispatch_id = reply["dispatch_id"]
        activity.logger.info(f"[dispatch]   order {order.order_id}: driver dispatched ({dispatch_id})")
        return dispatch_id
