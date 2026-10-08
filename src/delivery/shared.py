"""Constants shared by the Worker, the Workflow, and the tests."""

from pathlib import Path

# Where the demo writes what it keeps between runs: each managed process's log
# and each stub's ledger. It sits beside the source rather than inside the
# package, because the demo runs from the repo.
LOG_DIRECTORY = Path(__file__).resolve().parents[2] / "logs"

# The Task Queue the Worker polls and clients target.
TASK_QUEUE = "delivery"

# Where the Temporal frontend listens (the docker-compose dev server).
TEMPORAL_TARGET = "localhost:7233"

# Where the payment service stub listens.
PAYMENT_PORT = 8081
PAYMENT_URL = f"http://localhost:{PAYMENT_PORT}"

# Where the restaurant service stub listens.
RESTAURANT_PORT = 8082
RESTAURANT_URL = f"http://localhost:{RESTAURANT_PORT}"

# Where the dispatch service stub listens.
DISPATCH_PORT = 8083
DISPATCH_URL = f"http://localhost:{DISPATCH_PORT}"

# Where the order app listens. The control plane places orders through it rather
# than starting Workflows itself, so that killing the app really does stop new
# orders.
ORDER_APP_PORT = 8084
ORDER_APP_URL = f"http://localhost:{ORDER_APP_PORT}"
