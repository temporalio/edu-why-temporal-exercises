"""Place one order and print the charge.

A convenience for running the demo by hand. With the dev server, the payment
stub, and the Worker up, `make run` starts an OrderWorkflow so you can watch it
in the Web UI. The real client is the control plane in a later PR.

    uv run python -m delivery.starter
"""

import asyncio
import uuid

from temporalio.client import Client

from delivery.models import Order
from delivery.shared import TASK_QUEUE, TEMPORAL_TARGET
from delivery.workflows import OrderWorkflow


async def main() -> None:
    order = Order(
        order_id=f"order-{uuid.uuid4().hex[:8]}",
        amount_cents=1999,
        description="Pad Thai",
    )
    client = await Client.connect(TEMPORAL_TARGET)
    handle = await client.start_workflow(
        OrderWorkflow.run,
        order,
        id=order.order_id,
        task_queue=TASK_QUEUE,
    )
    print(f"Placed {order.order_id}. Watch it at http://localhost:8233")

    charge_id = await handle.result()
    print(f"Charged: {charge_id}")


if __name__ == "__main__":
    asyncio.run(main())
