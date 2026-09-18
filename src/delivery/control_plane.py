"""The control plane: the one backend the chaos panel talks to.

Everything the panel does goes through here. It reads the order's progress from
the Workflow, drives the supervisor to stop and start components, and serves the
panel itself, so the panel has a single origin and no CORS. It is the only thing
besides Temporal that the panel cannot switch off, because it is the thing doing
the switching.

Translating progress is its own job, and not a trivial one. The Workflow answers
with one of six keys naming where the order has got to; the panel draws five
steps, each needing a status. Two of those statuses aren't in the Workflow's
vocabulary: `waiting` separates the steps that park on a signal from the ones
that call a service, and `retrying` is inferred from a stopped service, because
the Workflow knows only that it is awaiting an Activity, not that the Activity
keeps failing.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from temporalio.client import Client

from delivery.shared import ORDER_APP_URL, TEMPORAL_TARGET
from delivery.supervisor import ProcessDefinition, Supervisor
from delivery.workflows import OrderWorkflow


@dataclass(frozen=True)
class PanelStep:
    """One step on the panel, and how to recognize the order sitting on it.

    `service` is the stub the step calls, or None when the step parks on a
    signal instead. That distinction is what separates a step that is `running`
    from one that is `waiting`.
    """

    key: str
    workflow_step: str
    service: Optional[str]


# The query's sixth key. It names no step, because by then the order has passed
# all five.
COMPLETE = "complete"

# How long to wait for the progress query before giving up on it.
#
# A Worker is what executes a query, so with none running the call doesn't fail,
# it waits, and the SDK's retries stretch that to about 29 seconds. The panel
# polls every 700ms, so an unbounded wait leaves it drawing nothing while
# requests stack up behind each other. Generous next to a healthy query, which
# answers in milliseconds.
PROGRESS_TIMEOUT_SECONDS = 2.0

# The panel's five steps in order. `key` is the panel's name for the step and
# `workflow_step` is what the progress query calls it, so this table is the only
# place the two vocabularies meet.
STEPS = [
    PanelStep(key="charge", workflow_step="charging_payment", service="payment"),
    PanelStep(key="restaurant", workflow_step="sending_to_restaurant", service="restaurant"),
    PanelStep(key="kitchen", workflow_step="waiting_for_kitchen", service=None),
    PanelStep(key="dispatch", workflow_step="dispatching_driver", service="dispatch"),
    PanelStep(key="delivery", workflow_step="waiting_for_delivery", service=None),
]


# The three steps that call out to a service, which are the only ones that can
# be retrying.
SERVICES = tuple(step.service for step in STEPS if step.service)


def panel_steps(current_step: str, services_down: set) -> list[dict]:
    """Every panel step with the status to draw it in, given where the order is.

    One reported step fixes all five: what the order has passed is done, what
    lies ahead is upcoming, and the step it sits on takes the status matching
    what that step is doing. For the step it sits on, that depends on whether
    the service it calls is running, since a call to a service that isn't there
    keeps failing rather than progressing.
    """
    if current_step == COMPLETE:
        reached = len(STEPS)  # past every step, so all five read as done
    else:
        reached = [step.workflow_step for step in STEPS].index(current_step)

    drawn = []

    for position, step in enumerate(STEPS):
        if position < reached:
            status = "done"
        elif position > reached:
            status = "upcoming"
        elif step.service is None:
            status = "waiting"  # parks on a signal rather than calling out
        elif step.service in services_down:
            status = "retrying"  # the service isn't there, so the call keeps failing
        else:
            status = "in-progress"

        drawn.append({"key": step.key, "status": status})

    return drawn


class PlacedOrder(BaseModel):
    order_id: str


class ComponentSwitch(BaseModel):
    """The desired state of one component, as the panel's checkbox sees it.

    Desired state rather than a `start` or `stop` verb, so that sending it twice
    means the same as sending it once. The panel control is a checkbox, and two
    clicks or two racing polls must not compound.
    """

    up: bool


async def place_order() -> str:
    """Ask the order app to start an order, and hand back its id."""
    async with httpx.AsyncClient() as http:
        response = await http.post(f"{ORDER_APP_URL}/orders")
        response.raise_for_status()

        return response.json()["order_id"]


# The panel's files, alongside the source rather than inside the package: this
# runs from the repo, not from an installed wheel.
PANEL_DIRECTORY = Path(__file__).resolve().parents[2] / "frontend"


async def connect_to_temporal() -> Client:
    return await Client.connect(TEMPORAL_TARGET)


# Each managed process's own log file lands here, beside the source rather than
# inside the package, for the same reason the panel does: this runs from the
# repo.
LOG_DIRECTORY = Path(__file__).resolve().parents[2] / "logs"

# The processes the control plane owns, keyed by **the panel's** names for them.
# `app` rather than `order-app`, because the panel froze that vocabulary when it
# was a mock and the backend conforms to it.
#
# The commands mirror the Makefile targets. That's a third copy of each port,
# after the Makefile and `shared.py`, and worth collapsing at some point.
#
# Each `match` is a module path, which satisfies the supervisor's requirement
# that the pattern appear in every process in the tree: `uv run python -m
# uvicorn delivery.stubs.payment:app` and the child it forks both carry it.
MANAGED_PROCESSES = {
    "payment": ProcessDefinition(
        command="uv run python -m uvicorn delivery.stubs.payment:app --port 8081",
        match="delivery.stubs.payment",
    ),
    "restaurant": ProcessDefinition(
        command="uv run python -m uvicorn delivery.stubs.restaurant:app --port 8082",
        match="delivery.stubs.restaurant",
    ),
    "dispatch": ProcessDefinition(
        command="uv run python -m uvicorn delivery.stubs.dispatch:app --port 8083",
        match="delivery.stubs.dispatch",
    ),
    "app": ProcessDefinition(
        command="uv run python -m uvicorn delivery.order_app:app --port 8084",
        match="delivery.order_app",
    ),
    "worker": ProcessDefinition(
        command="uv run python -m delivery.worker",
        match="delivery.worker",
    ),
}

# The five names the panel toggles, in the order the panel lists them.
COMPONENTS = tuple(MANAGED_PROCESSES)

# The one component the progress query depends on.
WORKER = "worker"

# The signals the panel can send, in the order their waits occur. Reporting
# them in this order rather than the order they were sent keeps the response
# stable.
SIGNALS = ("order_prepared", "order_delivered")


def build_supervisor() -> Supervisor:
    return Supervisor(MANAGED_PROCESSES, log_dir=LOG_DIRECTORY)


def create_app(
    place_order: Callable[[], Awaitable[str]] = place_order,
    connect: Callable[[], Awaitable[Client]] = connect_to_temporal,
    supervisor: Callable[[], Supervisor] = build_supervisor,
) -> FastAPI:
    # Injected as a factory, like `connect`, and called here. A default of
    # `build_supervisor()` would be evaluated once at import, so every app would
    # share one supervisor's process table.
    supervisor = supervisor()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        """Bring the demo up alongside the control plane, and down with it.

        Starting is unconditional rather than going through the same check the
        toggle uses, because a leftover from an earlier run is exactly what
        needs clearing here, and `start` clears one before launching.
        """
        for name in COMPONENTS:
            supervisor.start(name)

        yield

        for name in COMPONENTS:
            supervisor.stop(name)

    app = FastAPI(title="Control plane", lifespan=lifespan)

    client: Optional[Client] = None

    # The order the panel is currently showing. The id arrives on the way back
    # from placing one, which is why placing goes through here at all: nothing
    # else then has to be told which order is the current one.
    current_order_id: Optional[str] = None

    # The last progress we could confirm, for the order above. Served when the
    # query can't answer, so the panel keeps showing where that order got to
    # rather than going blank. It belongs to that order and nothing else, which
    # is why placing a new one clears it.
    last_known_steps: Optional[list] = None

    # Which signals have been sent for the order above. The Workflow holds the
    # real flags, but reading them takes a query and a query takes a Worker, so
    # with the Worker stopped it cannot be asked. The control plane sent them,
    # so it knows either way.
    signals_sent: set = set()

    async def temporal() -> Client:
        nonlocal client
        if client is None:
            client = await connect()

        return client

    @app.post("/orders", response_model=PlacedOrder)
    async def post_order() -> PlacedOrder:
        nonlocal current_order_id, last_known_steps
        current_order_id = await place_order()
        # Neither the old order's progress nor its signals belong to this one.
        last_known_steps = None
        signals_sent.clear()

        return PlacedOrder(order_id=current_order_id)

    async def current_order():
        """A handle on the order the panel is showing."""
        return (await temporal()).get_workflow_handle(current_order_id)

    # The panel's two Finish buttons. They stand in for the kitchen and the
    # driver, which in the real world report back on their own; nothing else
    # sends these signals to an order placed from the panel.
    #
    # Each records itself only once the signal is away, so a send that fails
    # is not remembered as having happened.

    @app.post("/signals/order_prepared")
    async def post_order_prepared() -> dict:
        await (await current_order()).signal(OrderWorkflow.order_prepared)
        signals_sent.add("order_prepared")

        return {}

    @app.post("/signals/order_delivered")
    async def post_order_delivered() -> dict:
        driver_id = f"drv-{uuid.uuid4().hex[:8]}"
        await (await current_order()).signal(OrderWorkflow.order_delivered, driver_id)
        signals_sent.add("order_delivered")

        return {}

    @app.put("/components/{name}")
    async def put_component(name: str, switch: ComponentSwitch) -> dict:
        """Bring a component to the state the panel asked for.

        Does nothing when it is already in that state. That matters for the
        Worker: `start` clears any earlier instance before launching, so acting
        on a healthy process kills it and puts a replacement in its place, which
        on the Worker means bouncing it mid-order.

        The response reports what the supervisor says rather than echoing the
        request, so the panel is told the truth when the two disagree.
        """
        if name not in COMPONENTS:
            raise HTTPException(status_code=404, detail=f"No component named {name!r}")

        running = supervisor.is_running(name)

        if switch.up and not running:
            supervisor.start(name)
        elif running and not switch.up:
            supervisor.stop(name)

        return {"name": name, "up": supervisor.is_running(name)}

    @app.get("/state")
    async def get_state() -> dict:
        """Everything the panel polls for, in one response.

        The components ride along with the order rather than getting their own
        endpoint, because the panel already polls this every 700ms and a second
        poll would double the traffic to learn something this one can carry.
        """
        nonlocal last_known_steps

        # Read from the supervisor rather than guessed. It is the only thing
        # that knows, and the step translation below needs it too: a stopped
        # service is what separates a step that is working from one that is
        # stuck retrying.
        components = {name: supervisor.is_running(name) for name in COMPONENTS}
        services_down = {name for name in SERVICES if not components[name]}

        order = None

        if current_order_id is not None:
            current_step = None

            # Only a Worker executes a query, so with none running the call
            # cannot succeed. It waits and then times out, so don't make it.
            if supervisor.is_running(WORKER):
                try:
                    current_step = await asyncio.wait_for(
                        (await current_order()).query(OrderWorkflow.current_step),
                        PROGRESS_TIMEOUT_SECONDS,
                    )
                except Exception:
                    # Broad on purpose. Any reason the query didn't answer means
                    # the same thing: we can't confirm where the order is. Only
                    # the query sits inside the try, so a real bug in the
                    # translation below still surfaces.
                    pass

            if current_step is None:
                # Unconfirmed. The last known steps are reported rather than
                # nothing, so a reader still sees where the order got to, and
                # the flag is what lets them know it may have moved since.
                order = {
                    "id": current_order_id,
                    "steps": last_known_steps or [],
                    "progress_confirmed": False,
                }
            else:
                last_known_steps = panel_steps(current_step, services_down)
                order = {
                    "id": current_order_id,
                    "steps": last_known_steps,
                    "progress_confirmed": True,
                }

        return {
            "order": order,
            "components": components,
            "signals_sent": [signal for signal in SIGNALS if signal in signals_sent],
        }

    # Mounted last, so the routes above still match first. `html=True` serves
    # index.html at the root, which is the whole panel.
    app.mount("/", StaticFiles(directory=PANEL_DIRECTORY, html=True), name="panel")

    return app


app = create_app()
