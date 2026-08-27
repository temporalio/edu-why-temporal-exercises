"""Workflows: the deterministic code Temporal runs and can recover.

`OrderWorkflow` is the heart of the demo. It runs the order's steps in sequence,
so far charge payment and send to restaurant, each with a retry policy and a
timeout, and returns an `OrderResult`. Kitchen, dispatch, and delivery steps come
with later PRs, each adding a field to the result rather than changing its shape.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from delivery.activities import charge_payment, send_to_restaurant
    from delivery.models import Order, OrderResult

# Each service call shares one timeout and retry policy. The backoff is capped at
# 10s (vs the 100s default) so a recovered service retries promptly and the demo's
# recovery stays visible.
_TIMEOUT = timedelta(seconds=10)
_RETRY = RetryPolicy(maximum_interval=timedelta(seconds=10))


@workflow.defn
class OrderWorkflow:
    @workflow.run
    async def run(self, order: Order) -> OrderResult:
        charge_id = await workflow.execute_activity(
            charge_payment,
            order,
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )
        ticket_id = await workflow.execute_activity(
            send_to_restaurant,
            order,
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )
        return OrderResult(
            order_id=order.order_id,
            charge_id=charge_id,
            ticket_id=ticket_id,
        )
