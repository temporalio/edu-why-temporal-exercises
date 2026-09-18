# edu-why-temporal-exercises

Hands-on code for **Why Temporal**, an introduction to the problem Temporal solves and why durable execution matters.

This is the **code** repository. It holds the source for hands-on exercises, instructor demonstrations, and reference samples, and it must be **public** so the exercise environment can provision it.

## Quickstart

You'll need [uv](https://docs.astral.sh/uv/) and Docker.

```sh
uv sync            # install dependencies
make test          # run the test suite (no Docker needed)
```

To run the demo, two commands in separate terminals:

```sh
make temporal        # the Temporal dev server (Web UI at http://localhost:8233)
make control-plane   # the chaos panel at http://localhost:8085, and everything it manages
```

Then open http://localhost:8085 and place an order.

The control plane launches the three service stubs, the order app, and the Worker, and stops them when it shuts down. It has to be the thing that starts them, because it can only stop what it started, and that is what makes the panel's toggles real rather than cosmetic. Temporal itself stays in Docker, since the demo never switches it off.

`make help` lists the available commands. The layout: the app lives in `src/delivery/` (`workflows.py`, `activities.py`, `worker.py`, `order_app.py`, and the service stubs under `stubs/`), the panel in `frontend/`, tests in `tests/`, and the Temporal dev server in `docker-compose.yml`.