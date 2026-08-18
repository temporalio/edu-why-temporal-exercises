"""Workflows: the deterministic code Temporal runs and can recover.

`OrderWorkflow` is the heart of the demo. For now it runs a single step, charge
payment, with a retry policy and a timeout. PR 3 adds the remaining steps:
restaurant, kitchen, dispatch, and delivery.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from delivery.activities import charge_payment
    from delivery.models import Order


@workflow.defn
class OrderWorkflow:
    @workflow.run
    async def run(self, order: Order) -> str:
        return await workflow.execute_activity(
            charge_payment,
            order,
            start_to_close_timeout=timedelta(seconds=10),
            # Default retry policy, but cap the backoff at 10s (vs the 100s
            # default) so a recovered service retries promptly and the demo's
            # recovery stays visible.
            retry_policy=RetryPolicy(maximum_interval=timedelta(seconds=10)),
        )
