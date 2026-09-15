"""The order app: the demo's front door.

It takes a place-order request, starts an OrderWorkflow, and hands back the
order's id. It does not wait for the order to finish, because the Workflow
outlives the request. That separation is exactly what the app-down toggle
demonstrates: kill this service and no new orders can be placed, while anything
already running carries on without it, because Temporal is executing the order
rather than this process.

Nothing here limits the demo to one order at a time. The panel disables its
button while an order is in flight, and for now that is the only thing enforcing
it.

    uv run python -m uvicorn delivery.order_app:app --port 8084
"""

import uuid
from typing import Awaitable, Callable

from fastapi import FastAPI
from pydantic import BaseModel
from temporalio.client import Client

from delivery.models import Order
from delivery.shared import TASK_QUEUE, TEMPORAL_TARGET
from delivery.workflows import OrderWorkflow

# The learner types nothing, so every order is the same order.
ORDER_AMOUNT_CENTS = 1999
ORDER_DESCRIPTION = "Pad Thai"


class PlacedOrder(BaseModel):
    order_id: str


async def connect_to_temporal() -> Client:
    return await Client.connect(TEMPORAL_TARGET)


def create_app(connect: Callable[[], Awaitable[Client]] = connect_to_temporal) -> FastAPI:
    app = FastAPI(title="Order app")
    client: Client = None

    @app.post("/orders", response_model=PlacedOrder)
    async def place_order() -> PlacedOrder:
        nonlocal client
        if client is None:
            client = await connect()

        order = Order(
            order_id=f"order-{uuid.uuid4().hex[:8]}",
            amount_cents=ORDER_AMOUNT_CENTS,
            description=ORDER_DESCRIPTION,
        )

        await client.start_workflow(
            OrderWorkflow.run,
            order,
            id=order.order_id,
            task_queue=TASK_QUEUE,
        )

        return PlacedOrder(order_id=order.order_id)

    return app


app = create_app()
