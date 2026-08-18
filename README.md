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

`make help` lists the available commands. The layout: the app lives in `src/delivery/` (`workflows.py`, `activities.py`, `worker.py`, and the service stubs under `stubs/`), tests in `tests/`, and the Temporal dev server in `docker-compose.yml`.