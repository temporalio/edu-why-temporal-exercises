# edu-why-temporal-exercises

Hands-on code for **Why Temporal**, an introduction to the problem Temporal solves and why durable execution matters.

This is the **code** repository. It holds the demo app behind the course's hands-on exercises, and the Instruqt track that runs it. It must be **public** so the exercise environment can provision it.

## What it is

The course is no-code, so there's no learner-written exercise code here. The hands-on part is a single browser-driven demo, the **Chaos Panel**, built around one food-delivery order. Learners place an order, then break the system around it and watch the order survive. The three Instruqt exercises look at that same demo through three lenses:

- **Reliability:** switch off services, kill the Worker, take down the order app, and watch the order wait, retry and resume without double-charging.
- **Insight:** open the real Temporal Web UI for the same run and read its Event History: each step, each wait, each retry and the Worker crash.
- **Velocity:** the panel, opened at `/?velocity`, adds a list of what Temporal handled during the order, and the exercise sets it against the machinery a team would otherwise build.

## Quickstart

You'll need [uv](https://docs.astral.sh/uv/) and Docker.

```sh
uv sync            # install dependencies
make test          # run the test suite (no Docker needed)
```

To run the demo, two commands in separate terminals:

```sh
make temporal        # the Temporal dev server (Web UI at http://localhost:8233)
make control-plane   # the Chaos Panel at http://localhost:8085, and everything it manages
```

Then open http://localhost:8085 and place an order. Open http://localhost:8085/?velocity for the Velocity exercise's version of the panel.

`make help` lists the available commands.

## How it's built

The app lives in `src/delivery/`, the panel in `frontend/`, tests in `tests/`, and the Temporal dev server in `docker-compose.yml`. Each component is a separate process:

- **Temporal:** the dev server and Web UI, from its prebuilt Docker image. It's the durable foundation the demo rests on, so it's the one thing that stays up throughout. It keeps everything in memory, which gives each session a clean slate.
- **Order Workflow** (`workflows.py`): five sequential steps. The three service calls (charge payment, send to the restaurant, dispatch a driver) are Activities with a retry policy whose wait between attempts tops out at 10 seconds. The two waits (kitchen prep, delivery) park on an external Signal, since a real kitchen or driver reports back rather than finishing on a clock. The `current_step` Query reports where the order has got to.
- **Service stubs** (`stubs/`): payment, restaurant and dispatch. Each is a plain service with no chaos machinery of its own. "Off" means the process is stopped, so calls fail and the step retries until it's back. Each keeps a ledger on disk and acts once per order, however many times it's called, which is what makes retries safe. Payment and dispatch include a short delay so their steps are visible on the panel.
- **Worker** (`worker.py`): runs the Workflow. It's stopped with `kill -9`, an ungraceful crash, and resumes where the order left off when it's restarted.
- **Order app** (`order_app.py`): the front door. It accepts a place-order request and starts the Workflow. With it down, no new orders can be placed, but an order already running carries on, because Temporal, not the app, is running it.
- **Process supervisor** (`supervisor.py`): starts, stops and reports on the processes above, each writing to its own log in `logs/`. It doesn't wait for a restarted process to be ready, since Temporal retries until the service answers.
- **Control plane** (`control_plane.py`): the backend the panel talks to, and the only thing besides Temporal the panel can't switch off. It launches every managed process, which is what makes the toggles real, since the supervisor can only stop what it started. It serves the panel, proxies place-order requests through the order app (so the app-down lesson stays honest), reads the order's progress, and sends the two Signals on the learner's behalf.

### Design decisions

- **Nothing fakes being down.** Every component the panel switches off is a real process that gets stopped and started. No service has a "pretend I'm broken" flag.
- **Transient failures only.** Every step succeeds eventually once its service is back. Permanent failures and rollbacks belong to later courses.
- **Idempotency in the services, not in Temporal.** Temporal retries; the services make a repeated call harmless. The panel's ledgers show it, and the exercises say so.
- **One order at a time.** The panel disables Place order while an order is running. That's the only thing enforcing it.
- **The panel infers `retrying`.** The Workflow only knows it's waiting on an Activity, not that the Activity keeps failing, so the control plane infers retrying from a stopped service. It also checks the Worker is up before querying, because with the Worker down a Query waits for its full timeout rather than failing fast.
- **A plain HTML and JavaScript panel, with no build step,** polling the control plane for updates. It's dark-themed on Temporal's brand palette, to match Instruqt.

## The Instruqt track

The track lives in `instruqt/`: `track.yml`, one folder per exercise (`01-reliability`, `02-insight`, `03-velocity`), screenshots in `assets/`, and the setup script in `track_scripts/`.

- **The sandbox image** (`sandbox/Dockerfile`) has Python, uv, the Temporal CLI and this repo installed, so starting a lab only starts processes. The panel is built into the image, so any change to `frontend/` or `src/` needs the image rebuilt for `linux/amd64`, pushed to `ghcr.io/temporalio/why-temporal-sandbox`, and its new digest set in `instruqt/config.yml`.
- **Screenshots** come from `instruqt/tools/`: `capture-panel-screenshots.mjs` for the panel and `capture-ui-screenshots.mjs` for the Temporal UI. Each drives a running demo through its API and captures it in headless Chrome. See each script's header for how to run it.
- **Pushing:** `instruqt track push` from `instruqt/`. Skipping challenges is turned off for learners (`skipping_enabled: false`). After a push, the CLI rewrites `track.yml` and drops that line, because it leaves out settings that are false. The setting stays off.

## Testing

`make test` runs the suite with `pytest`, using Temporal's time-skipping test server, so it doesn't need Docker. It covers the Workflow (each step retrying through a failure, the two Signal waits, and the progress Query), the Activities, the stubs (including that each acts only once per order, even after a restart), the supervisor and the control plane.

Anything that depends on really killing a process, such as a service outage or the Worker crash and resume, isn't automated. Each side of those boundaries is tested, and the whole is checked by running the demo.
