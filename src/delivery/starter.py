"""Start one workflow and print its result.

A convenience for running the demo by hand. With the dev server and worker up,
`make run` fires a workflow through the live worker so you can watch the whole
path in the Web UI. The real client is the control plane in a later PR; this is
a stopgap so there's something to run today.

    uv run python -m delivery.starter [name]
"""

import asyncio
import sys
import uuid

from temporalio.client import Client

from delivery.shared import TASK_QUEUE, TEMPORAL_TARGET
from delivery.workflows import GreetingWorkflow


async def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "world"
    client = await Client.connect(TEMPORAL_TARGET)

    workflow_id = f"greeting-{uuid.uuid4()}"
    handle = await client.start_workflow(
        GreetingWorkflow.run,
        name,
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )
    print(f"Started {workflow_id} — watch it at http://localhost:8233")

    result = await handle.result()
    print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
