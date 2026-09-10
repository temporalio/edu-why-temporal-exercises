"""Workflows: the deterministic code Temporal runs and can recover.

`OrderWorkflow` is the heart of the demo. It runs the order's steps in sequence,
so far charge payment, send to restaurant, wait for the kitchen, and dispatch a
driver, each with a retry policy and a timeout where it calls a service, and
returns an `OrderResult`. The delivery step comes with a later PR, adding a field
to the result rather than changing its shape.
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

    @workflow.signal
    def kitchen_ready(self) -> None:
        """The kitchen reports the food is ready. Sent by the simulated kitchen."""
        self._kitchen_ready = True

    @workflow.run
    async def run(self, order: Order) -> OrderResult:
        workflow.logger.info(f"[order]      order {order.order_id}: started")

        workflow.logger.info(f"[order]      order {order.order_id}: charging payment")
        charge_id = await workflow.execute_activity(
            charge_payment,
            order,
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )

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
        workflow.logger.info(f"[order]      order {order.order_id}: waiting on the kitchen")
        await workflow.wait_condition(lambda: self._kitchen_ready)
        workflow.logger.info(f"[order]      order {order.order_id}: kitchen ready")

        workflow.logger.info(f"[order]      order {order.order_id}: dispatching a driver")
        dispatch_id = await workflow.execute_activity(
            dispatch_driver,
            order,
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )
        
        workflow.logger.info(f"[order]      order {order.order_id}: complete")
        return OrderResult(
            order_id=order.order_id,
            charge_id=charge_id,
            ticket_id=ticket_id,
            dispatch_id=dispatch_id,
        )
