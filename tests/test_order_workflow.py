"""OrderWorkflow charges the order, sends it to the restaurant, dispatches a
driver, waits for delivery, and returns the results as an OrderResult.

The Activities are mocked here so we test the Workflow's orchestration in
isolation: that it runs each step and returns its result. The real HTTP path to
the stubs is covered by the integration test in a later PR.
"""

import asyncio
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

    Both signals are sent up front, before the order reaches either wait. That's
    safe: the flags are durable, so an early signal just pre-sets one and
    wait_condition passes straight through. Tests that exercise a wait itself send
    their own signals.
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
        await handle.signal("kitchen_ready")
        await handle.signal("delivered", f"drv-{order.order_id}")
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

            # Release the kitchen wait, then report delivery so the order can finish.
            await handle.signal("kitchen_ready")
            await handle.signal("delivered", f"drv-{order.order_id}")
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


async def wait_for_step(handle, expected: str) -> str:
    """The Workflow's reported step, once it settles on `expected`.

    Returns whatever it last said, so a failed assertion names the state the
    order was really in rather than just reporting a timeout.
    """
    seen = ""

    for _ in range(250):
        seen = await handle.query(OrderWorkflow.current_step)
        if seen == expected:
            return seen
        await asyncio.sleep(0.02)

    return seen


async def test_the_progress_query_names_every_state_in_turn():
    """The panel reads the order's position by asking the Workflow.

    The Workflow already knows where it is, so asking it is a more honest source
    than inferring the position from event history. It answers with one of six
    stable keys, one per step on the panel plus `complete`, so there is nothing
    for the panel to derive.

    The keys say nothing about retrying. The Workflow only knows it is awaiting
    an Activity, not that the Activity keeps failing, so that gets inferred from
    the service being stopped instead.

    Each Activity is held open until this test releases it, which pins every
    state long enough to ask about. Letting the Activities merely be slow would
    make this a race, and a state that passes too quickly is a state the test
    skips without telling anyone.
    """
    release_charge = asyncio.Event()
    release_restaurant = asyncio.Event()
    release_dispatch = asyncio.Event()

    @activity.defn(name="charge_payment")
    async def held_charge(order: Order) -> str:
        await release_charge.wait()
        return f"ch-{order.order_id}"

    @activity.defn(name="send_to_restaurant")
    async def held_restaurant(order: Order) -> str:
        await release_restaurant.wait()
        return f"tkt-{order.order_id}"

    @activity.defn(name="dispatch_driver")
    async def held_dispatch(order: Order) -> str:
        await release_dispatch.wait()
        return f"dsp-{order.order_id}"

    order = an_order()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[OrderWorkflow],
            activities=[held_charge, held_restaurant, held_dispatch],
        ):
            handle = await env.client.start_workflow(
                OrderWorkflow.run,
                order,
                id=order.order_id,
                task_queue=TASK_QUEUE,
            )

            assert await wait_for_step(handle, "charging_payment") == "charging_payment"

            release_charge.set()
            assert await wait_for_step(handle, "sending_to_restaurant") == "sending_to_restaurant"

            release_restaurant.set()
            assert await wait_for_step(handle, "waiting_for_kitchen") == "waiting_for_kitchen"

            await handle.signal("kitchen_ready")
            assert await wait_for_step(handle, "dispatching_driver") == "dispatching_driver"

            release_dispatch.set()
            assert await wait_for_step(handle, "waiting_for_delivery") == "waiting_for_delivery"

            await handle.signal("delivered", f"drv-{order.order_id}")
            await handle.result()
            assert await handle.query(OrderWorkflow.current_step) == "complete"
