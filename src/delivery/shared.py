"""Constants shared by the Worker, the Workflow, and the tests."""

# The task queue the worker polls and clients target.
TASK_QUEUE = "delivery"

# Where the Temporal frontend listens (the docker-compose dev server).
TEMPORAL_TARGET = "localhost:7233"
