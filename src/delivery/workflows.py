"""Workflows: the deterministic code Temporal runs and can recover.

For now this is a single trivial workflow that calls one activity end to end,
just enough to prove the scaffold holds together. PR 2 replaces it with the
real five-step order workflow.
"""

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from delivery.activities import say_hello


@workflow.defn
class GreetingWorkflow:
    @workflow.run
    async def run(self, name: str) -> str:
        return await workflow.execute_activity(
            say_hello,
            name,
            start_to_close_timeout=timedelta(seconds=10),
        )
