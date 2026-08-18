"""Constants shared by the Worker, the Workflow, and the tests."""

# The Task Queue the Worker polls and clients target.
TASK_QUEUE = "delivery"

# Where the Temporal frontend listens (the docker-compose dev server).
TEMPORAL_TARGET = "localhost:7233"

# Where the payment service stub listens.
PAYMENT_URL = "http://localhost:8081"
