"""Smoke test: the trivial workflow runs end to end.

Uses Temporal's time-skipping test server, so it needs no running Docker. The
`run_greeting` helper is the shape every later test follows: it owns the
worker's lifecycle and returns the workflow's result, so a test is just inputs
in, result out, assertion.
"""

import uuid

from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from delivery.activities import say_hello
from delivery.shared import TASK_QUEUE
from delivery.workflows import GreetingWorkflow


async def run_greeting(client: Client, name: str) -> str:
    """Run the greeting workflow under a worker and return its result."""
    async with Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[GreetingWorkflow],
        activities=[say_hello],
    ):
        return await client.execute_workflow(
            GreetingWorkflow.run,
            name,
            id=f"greeting-{uuid.uuid4()}",
            task_queue=TASK_QUEUE,
        )


async def test_greeting_workflow_runs_end_to_end():
    async with await WorkflowEnvironment.start_time_skipping() as env:
        result = await run_greeting(env.client, "world")
        assert result == "Hello, world!"
