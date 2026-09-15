# edu-why-temporal-exercises

Hands-on code for **Why Temporal**, an introduction to the problem Temporal solves and why durable execution matters.

This is the **code** repository. It holds the source for hands-on exercises, instructor demonstrations, and reference samples, and it must be **public** so the exercise environment can provision it.

## Quickstart

You'll need [uv](https://docs.astral.sh/uv/) and Docker.

```sh
uv sync            # install dependencies
make test          # run the test suite (no Docker needed)
```

To run the demo, in separate terminals:

```sh
make temporal      # the Temporal dev server (Web UI at http://localhost:8233)
make payment       # the payment service stub
make worker        # the Worker, polling the "delivery" queue
make run           # place an order and watch it charge
```

`make run` places an order directly. The order app is the front door the panel
will use instead, and it's the service the app-down toggle switches off:

```sh
make order-app     # the front door at http://localhost:8084
curl -X POST http://localhost:8084/orders
```

The chaos panel UI serves separately (currently a standalone mock, every interaction faked in the browser):

```sh
make panel         # the chaos panel at http://localhost:8080
```

`make help` lists the available commands. The layout: the app lives in `src/delivery/` (`workflows.py`, `activities.py`, `worker.py`, `order_app.py`, and the service stubs under `stubs/`), the panel in `frontend/`, tests in `tests/`, and the Temporal dev server in `docker-compose.yml`.