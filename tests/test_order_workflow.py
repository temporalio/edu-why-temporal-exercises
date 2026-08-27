"""OrderWorkflow charges the order, sends it to the restaurant, and returns both
results as an OrderResult.

The Activities are mocked here so we test the Workflow's orchestration in
isolation: that it runs both steps and returns their results. The real HTTP path
to the stubs is covered by the integration test in a later PR.
"""

import uuid

from temporalio import activity
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from delivery.models import Order
from delivery.shared import TASK_QUEUE
from delivery.workflows import OrderWorkflow


async def run_order(client: Client, order: Order, activities: list):
    """Run OrderWorkflow under a Worker with the given Activities."""
    async with Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[OrderWorkflow],
        activities=activities,
    ):
        return await client.execute_workflow(
            OrderWorkflow.run,
            order,
            id=order.order_id,
            task_queue=TASK_QUEUE,
        )


def an_order() -> Order:
    return Order(order_id=f"order-{uuid.uuid4().hex[:8]}", amount_cents=1999)


@activity.defn(name="charge_payment")
async def ok_charge(order: Order) -> str:
    return f"ch-{order.order_id}"


@activity.defn(name="send_to_restaurant")
async def ok_restaurant(order: Order) -> str:
    return f"tkt-{order.order_id}"


async def test_order_runs_both_steps_and_returns_result():
    order = an_order()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        result = await run_order(env.client, order, [ok_charge, ok_restaurant])

    assert result.order_id == order.order_id
    assert result.charge_id == f"ch-{order.order_id}"
    assert result.ticket_id == f"tkt-{order.order_id}"


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
        result = await run_order(env.client, order, [flaky_charge, ok_restaurant])

    assert result.charge_id == f"ch-{order.order_id}"
    assert len(attempts) == 2  # failed once, retried, then succeeded


async def test_restaurant_is_retried_then_completes():
    attempts: list[int] = []

    @activity.defn(name="send_to_restaurant")
    async def flaky_restaurant(order: Order) -> str:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("restaurant service unavailable")
        return f"tkt-{order.order_id}"

    order = an_order()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        result = await run_order(env.client, order, [ok_charge, flaky_restaurant])

    assert result.ticket_id == f"tkt-{order.order_id}"
    assert len(attempts) == 2  # failed once, retried, then succeeded
