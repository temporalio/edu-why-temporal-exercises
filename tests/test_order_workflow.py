"""OrderWorkflow charges the order and retries the charge until it succeeds.

The Activity is mocked here so we test the Workflow's orchestration in isolation:
that it calls the charge, and that a transient failure is retried to completion.
The real HTTP path to the payment stub is covered by the integration test in a
later PR.
"""

import uuid

from temporalio import activity
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from delivery.models import Order
from delivery.shared import TASK_QUEUE
from delivery.workflows import OrderWorkflow


async def run_order(client: Client, order: Order, charge_activity) -> str:
    """Run OrderWorkflow under a Worker with the given charge Activity."""
    async with Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[OrderWorkflow],
        activities=[charge_activity],
    ):
        return await client.execute_workflow(
            OrderWorkflow.run,
            order,
            id=order.order_id,
            task_queue=TASK_QUEUE,
        )


def an_order() -> Order:
    return Order(order_id=f"order-{uuid.uuid4().hex[:8]}", amount_cents=1999)


async def test_order_charges_and_completes():
    charged: list[str] = []

    @activity.defn(name="charge_payment")
    async def fake_charge(order: Order) -> str:
        charged.append(order.order_id)
        return f"ch-{order.order_id}"

    order = an_order()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        result = await run_order(env.client, order, fake_charge)

        assert result == f"ch-{order.order_id}"
        assert charged == [order.order_id]


async def test_charge_is_retried_then_completes():
    attempts: list[int] = []

    @activity.defn(name="charge_payment")
    async def flaky_charge(order: Order) -> str:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("payment service unavailable")
        return f"ch-{order.order_id}"

    order = an_order()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        result = await run_order(env.client, order, flaky_charge)

        assert result == f"ch-{order.order_id}"
        assert len(attempts) == 2  # failed once, retried, then succeeded
