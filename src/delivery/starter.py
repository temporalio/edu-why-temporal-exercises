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

    # Stand in for the (eventual) simulated kitchen: after a short prep, report the
    # order ready so it clears the kitchen wait. In the real demo this signal comes
    # from a separate kitchen service, not from the client.
    await asyncio.sleep(3)
    await handle.signal(OrderWorkflow.kitchen_ready)
    print("(stand-in kitchen) reported the order ready")

    # Stand in for the (eventual) simulated driver: after the run to the door, report
    # the order delivered, naming the driver, so it clears the delivery wait. In the
    # real demo this signal comes from the driver, not the client.
    await asyncio.sleep(3)
    driver_id = f"drv-{uuid.uuid4().hex[:8]}"
    await handle.signal(OrderWorkflow.delivered, driver_id)
    print(f"(stand-in driver) {driver_id} reported the order delivered")

    result = await handle.result()
    print(f"Order {result.order_id} complete. (Per-step detail is in the Worker log.)")


if __name__ == "__main__":
    asyncio.run(main())
