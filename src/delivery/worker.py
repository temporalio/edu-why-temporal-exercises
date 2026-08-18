"""The worker: connects to Temporal, registers the workflow and activities,
and polls the task queue for work.

This is the process the demo crashes and restarts. Run it with the dev server
up: `make worker` (or `uv run python -m delivery.worker`).
"""

import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from delivery.activities import say_hello
from delivery.shared import TASK_QUEUE, TEMPORAL_TARGET
from delivery.workflows import GreetingWorkflow


async def main() -> None:
    client = await Client.connect(TEMPORAL_TARGET)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[GreetingWorkflow],
        activities=[say_hello],
    )
    print(f"Worker polling '{TASK_QUEUE}' at {TEMPORAL_TARGET} (Ctrl-C to stop)")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
