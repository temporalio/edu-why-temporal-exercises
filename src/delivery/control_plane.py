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
that call a service, and `retrying` will have to be inferred from a stopped
service, because the Workflow knows only that it is awaiting an Activity, not
that the Activity keeps failing. `retrying` waits on the supervisor: until the
control plane owns the service processes, nothing here can tell a stopped
service from a running one, so every service is assumed up.
"""

import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from temporalio.client import Client

from delivery.shared import ORDER_APP_URL, TEMPORAL_TARGET
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


def panel_steps(current_step: str) -> list[dict]:
    """Every panel step with the status to draw it in, given where the order is.

    One reported step fixes all five: what the order has passed is done, what
    lies ahead is upcoming, and the step it sits on takes the status matching
    what that step actually does.
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
        else:
            status = "in-progress"

        drawn.append({"key": step.key, "status": status})

    return drawn


class PlacedOrder(BaseModel):
    order_id: str


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


def create_app(
    place_order: Callable[[], Awaitable[str]] = place_order,
    connect: Callable[[], Awaitable[Client]] = connect_to_temporal,
) -> FastAPI:
    app = FastAPI(title="Control plane")

    client: Optional[Client] = None

    # The order the panel is currently showing. The id arrives on the way back
    # from placing one, which is why placing goes through here at all: nothing
    # else then has to be told which order is the current one.
    current_order_id: Optional[str] = None

    # The last progress we could confirm. Served when the query can't answer,
    # so the panel keeps showing where the order got to rather than going blank.
    last_known_steps: Optional[list] = None

    async def temporal() -> Client:
        nonlocal client
        if client is None:
            client = await connect()

        return client

    @app.post("/orders", response_model=PlacedOrder)
    async def post_order() -> PlacedOrder:
        nonlocal current_order_id
        current_order_id = await place_order()

        return PlacedOrder(order_id=current_order_id)

    async def current_order():
        """A handle on the order the panel is showing."""
        return (await temporal()).get_workflow_handle(current_order_id)

    # The panel's two Finish buttons. They stand in for the kitchen and the
    # driver, which in the real world report back on their own; nothing else
    # sends these signals to an order placed from the panel.
    #
    # Named `order_prepared` and `order_delivered` even though the Workflow's
    # signals are still `kitchen_ready` and `delivered`. The kitchen isn't what
    # is ready, the order is, and renaming the signals is a separate change.

    @app.post("/signals/order_prepared")
    async def post_order_prepared() -> dict:
        await (await current_order()).signal(OrderWorkflow.kitchen_ready)

        return {}

    @app.post("/signals/order_delivered")
    async def post_order_delivered() -> dict:
        driver_id = f"drv-{uuid.uuid4().hex[:8]}"
        await (await current_order()).signal(OrderWorkflow.delivered, driver_id)

        return {}

    @app.get("/state")
    async def get_state() -> dict:
        nonlocal last_known_steps

        if current_order_id is None:
            return {"order": None}

        try:
            current_step = await asyncio.wait_for(
                (await current_order()).query(OrderWorkflow.current_step),
                PROGRESS_TIMEOUT_SECONDS,
            )
        except Exception:
            # Broad on purpose. Any reason the query didn't answer means the
            # same thing to the panel: we can't confirm where the order is. The
            # response says so rather than hiding it, and the last known steps
            # keep the panel drawn instead of blank. Only the query sits inside
            # the try, so a real bug in the translation below still surfaces.
            return {
                "order": {
                    "id": current_order_id,
                    "steps": last_known_steps or [],
                    "progress_confirmed": False,
                }
            }

        last_known_steps = panel_steps(current_step)

        return {
            "order": {
                "id": current_order_id,
                "steps": last_known_steps,
                "progress_confirmed": True,
            }
        }

    # Mounted last, so the routes above still match first. `html=True` serves
    # index.html at the root, which is the whole panel.
    app.mount("/", StaticFiles(directory=PANEL_DIRECTORY, html=True), name="panel")

    return app


app = create_app()
