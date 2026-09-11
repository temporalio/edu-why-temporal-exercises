"""Workflows: the deterministic code Temporal runs and can recover.

`OrderWorkflow` is the heart of the demo. It runs the order's steps in sequence,
charge payment, send to restaurant, wait for the kitchen, dispatch a driver, and
wait for delivery, each service call with a retry policy and a timeout, and returns
an `OrderResult`. The two waits (kitchen, delivery) park on an external signal, the
honest model, since a real kitchen or driver reports back rather than finishing on
a clock.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from delivery.activities import charge_payment, dispatch_driver, send_to_restaurant
    from delivery.models import Order, OrderResult

# Each service call shares one timeout and retry policy. The backoff is capped at
# 10s (vs the 100s default) so a recovered service retries promptly and the demo's
# recovery stays visible.
_TIMEOUT = timedelta(seconds=10)
_RETRY = RetryPolicy(maximum_interval=timedelta(seconds=10))


@workflow.defn
class OrderWorkflow:
    def __init__(self) -> None:
        self._kitchen_ready = False
        self._delivered = False
        self._driver_id = ""
        self._current_step = ""  # run() names each step as the order reaches it

    @workflow.signal
    def kitchen_ready(self) -> None:
        """The kitchen reports the food is ready. Sent by the simulated kitchen."""
        self._kitchen_ready = True

    @workflow.signal
    def delivered(self, driver_id: str) -> None:
        """The driver reports the order delivered, naming themselves. Sent by the
        (simulated) driver; the id is who delivered this order."""
        self._driver_id = driver_id
        self._delivered = True

    @workflow.query
    def current_step(self) -> str:
        """Where the order has got to: one of six stable keys, one per step on the
        panel, plus `complete`.

        Deliberately silent about retrying. The Workflow only knows that it is
        awaiting an Activity, not that the Activity keeps failing, so that gets
        inferred from the service being stopped instead.
        """
        return self._current_step

    @workflow.run
    async def run(self, order: Order) -> OrderResult:
        workflow.logger.info(f"[order]      order {order.order_id}: started")

        self._current_step = "charging_payment"
        workflow.logger.info(f"[order]      order {order.order_id}: charging payment")
        charge_id = await workflow.execute_activity(
            charge_payment,
            order,
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )

        self._current_step = "sending_to_restaurant"
        workflow.logger.info(f"[order]      order {order.order_id}: sending to the restaurant")
        ticket_id = await workflow.execute_activity(
            send_to_restaurant,
            order,
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )

        # Kitchen prep: park until the kitchen signals the food is ready. A real
        # kitchen reports back when it's done rather than finishing on a clock, so
        # the honest model is to wait for an external signal, not a timer. This is
        # also the calm place to kill the Worker and watch the order resume.
        self._current_step = "waiting_for_kitchen"
        workflow.logger.info(f"[order]      order {order.order_id}: waiting on the kitchen")
        await workflow.wait_condition(lambda: self._kitchen_ready)
        workflow.logger.info(f"[order]      order {order.order_id}: kitchen ready")

        self._current_step = "dispatching_driver"
        workflow.logger.info(f"[order]      order {order.order_id}: dispatching a driver")
        dispatch_id = await workflow.execute_activity(
            dispatch_driver,
            order,
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )

        # Delivery: park until the driver reports the order delivered. Like the
        # kitchen, this is an external signal rather than a timer, and the signal
        # carries the id of the driver who delivered it. A second calm place to
        # kill the Worker and watch the order resume.
        self._current_step = "waiting_for_delivery"
        workflow.logger.info(f"[order]      order {order.order_id}: waiting on delivery")
        await workflow.wait_condition(lambda: self._delivered)
        workflow.logger.info(f"[order]      order {order.order_id}: delivered by {self._driver_id}")

        self._current_step = "complete"
        workflow.logger.info(f"[order]      order {order.order_id}: complete")
        return OrderResult(
            order_id=order.order_id,
            charge_id=charge_id,
            ticket_id=ticket_id,
            dispatch_id=dispatch_id,
            driver_id=self._driver_id,
        )
