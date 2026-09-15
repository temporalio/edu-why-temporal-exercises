"""Constants shared by the Worker, the Workflow, and the tests."""

# The Task Queue the Worker polls and clients target.
TASK_QUEUE = "delivery"

# Where the Temporal frontend listens (the docker-compose dev server).
TEMPORAL_TARGET = "localhost:7233"

# Where the payment service stub listens.
PAYMENT_URL = "http://localhost:8081"

# Where the restaurant service stub listens.
RESTAURANT_URL = "http://localhost:8082"

# Where the dispatch service stub listens.
DISPATCH_URL = "http://localhost:8083"

# Where the order app listens. The control plane places orders through it rather
# than starting Workflows itself, so that killing the app really does stop new
# orders.
ORDER_APP_URL = "http://localhost:8084"
