"""OrderWorkflow charges the order, sends it to the restaurant, dispatches a
driver, waits for delivery, and returns the results as an OrderResult.

The Activities are mocked here so we test the Workflow's orchestration in
isolation: that it runs each step and returns its result. The real HTTP path to
the stubs is covered by the integration test in a later PR.
"""

import uuid
from datetime import timedelta

from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from delivery.models import Order, OrderResult
from delivery.shared import TASK_QUEUE
from delivery.workflows import OrderWorkflow


async def run_order(client: Client, order: Order, activities: list) -> OrderResult:
    """Run OrderWorkflow under a Worker with the given Activities to completion.

    Sends both external signals so the order clears its two waits and finishes:
    the delivered signal (carrying a driver) first, then kitchen_ready. The tests
    that exercise a wait itself use their own flow. Signaling immediately is safe:
    the flags are durable, so an early signal just pre-sets them and wait_condition
    passes straight through. Delivered goes first so it lands while the order is
    still parked at the kitchen, never after it has already finished.
    """
    async with Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[OrderWorkflow],
        activities=activities,
    ):
        handle = await client.start_workflow(
            OrderWorkflow.run,
            order,
            id=order.order_id,
            task_queue=TASK_QUEUE,
        )
        await handle.signal("delivered", f"drv-{order.order_id}")
        await handle.signal("kitchen_ready")
        return await handle.result()


def an_order() -> Order:
    return Order(order_id=f"order-{uuid.uuid4().hex[:8]}", amount_cents=1999)


@activity.defn(name="charge_payment")
async def ok_charge(order: Order) -> str:
    return f"ch-{order.order_id}"


@activity.defn(name="send_to_restaurant")
async def ok_restaurant(order: Order) -> str:
    return f"tkt-{order.order_id}"


@activity.defn(name="dispatch_driver")
async def ok_dispatch(order: Order) -> str:
    return f"dsp-{order.order_id}"


async def test_order_runs_all_steps_and_returns_result():
    order = an_order()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        result = await run_order(env.client, order, [ok_charge, ok_restaurant, ok_dispatch])

    assert result.order_id == order.order_id
    assert result.charge_id == f"ch-{order.order_id}"
    assert result.ticket_id == f"tkt-{order.order_id}"
    assert result.dispatch_id == f"dsp-{order.order_id}"
    assert result.driver_id == f"drv-{order.order_id}"


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
        result = await run_order(env.client, order, [flaky_charge, ok_restaurant, ok_dispatch])

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
        result = await run_order(env.client, order, [ok_charge, flaky_restaurant, ok_dispatch])

    assert result.ticket_id == f"tkt-{order.order_id}"
    assert len(attempts) == 2  # failed once, retried, then succeeded


async def test_dispatch_is_retried_then_completes():
    attempts: list[int] = []

    @activity.defn(name="dispatch_driver")
    async def flaky_dispatch(order: Order) -> str:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("dispatch service unavailable")
        return f"dsp-{order.order_id}"

    order = an_order()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        result = await run_order(env.client, order, [ok_charge, ok_restaurant, flaky_dispatch])

    assert result.dispatch_id == f"dsp-{order.order_id}"
    assert len(attempts) == 2  # failed once, retried, then succeeded


async def test_order_waits_for_the_kitchen_signal():
    """The order parks at the kitchen until the kitchen_ready signal arrives: the
    passage of time alone does not advance it, only the signal does. (A sleep longer
    than the jump below would slip past this check; we're guarding against the order
    moving on its own with time, not against that narrower case.)"""
    order = an_order()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[OrderWorkflow],
            activities=[ok_charge, ok_restaurant, ok_dispatch],
        ):
            handle = await env.client.start_workflow(
                OrderWorkflow.run,
                order,
                id=order.order_id,
                task_queue=TASK_QUEUE,
            )

            # Skip well past any accidental delay, without signaling. Simulated time,
            # so it's instant; it also settles the workflow at its wait before we
            # inspect it, rather than racing the worker.
            await env.sleep(timedelta(minutes=5))

            # Time alone did not move the order on; it is still parked.
            assert (await handle.describe()).status == WorkflowExecutionStatus.RUNNING

            # Queue the delivery report, then release the kitchen wait.
            await handle.signal("delivered", f"drv-{order.order_id}")
            await handle.signal("kitchen_ready")
            result = await handle.result()

    assert result.order_id == order.order_id
    assert result.charge_id == f"ch-{order.order_id}"
    assert result.ticket_id == f"tkt-{order.order_id}"
    assert result.dispatch_id == f"dsp-{order.order_id}"
    assert result.driver_id == f"drv-{order.order_id}"


async def test_order_waits_for_the_delivered_signal():
    """After dispatch, the order parks until the driver signals delivery, and the
    signal carries the delivering driver's id. Time alone does not advance it."""
    order = an_order()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[OrderWorkflow],
            activities=[ok_charge, ok_restaurant, ok_dispatch],
        ):
            handle = await env.client.start_workflow(
                OrderWorkflow.run,
                order,
                id=order.order_id,
                task_queue=TASK_QUEUE,
            )

            # Clear the kitchen wait so the order advances to the delivery wait.
            await handle.signal("kitchen_ready")
            await env.sleep(timedelta(minutes=5))

            # Parked at delivery: time and a completed dispatch did not finish it.
            assert (await handle.describe()).status == WorkflowExecutionStatus.RUNNING

            # The delivered signal releases it and names the driver.
            await handle.signal("delivered", "drv-42")
            result = await handle.result()

    assert result.driver_id == "drv-42"
