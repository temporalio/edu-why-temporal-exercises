"""The control plane turns what the Workflow knows into what the panel draws.

The Workflow answers a progress query with one of six keys naming where the
order has got to. The panel needs something different: every step, each with a
status it can render. Nothing else in the system does that translation, and it
is not a detail, because two of the panel's five statuses are not in the
Workflow's vocabulary at all. `waiting` distinguishes the two steps that park on
a signal from the three that call a service, and `retrying` is inferred from a
stopped service, since the Workflow only knows it is awaiting an Activity, not
that the Activity keeps failing.

`retrying` doesn't appear yet. The supervisor reports which services are up, so
the information needed to infer it is here; using it is its own step.
"""

import asyncio
import time

from fastapi.testclient import TestClient

from delivery.control_plane import COMPONENTS, create_app, panel_steps
from delivery.workflows import OrderWorkflow


class FakeOrderApp:
    """Stands in for the order app, recording what the control plane asked it."""

    def __init__(self, order_id: str = "order-abc123") -> None:
        self.order_id = order_id
        self.calls = 0

    async def place_order(self) -> str:
        self.calls += 1
        return self.order_id


class FakeWorkflowHandle:
    """Answers the progress query with whatever step the test asked for."""

    def __init__(self, current_step: str) -> None:
        self.current_step = current_step
        self.queried: list = []
        self.signalled: list = []

    async def query(self, query):
        self.queried.append(query)
        return self.current_step

    async def signal(self, signal, *arguments):
        self.signalled.append((signal, arguments))


class HangingWorkflowHandle:
    """A handle whose query never answers, the way it behaves with no Worker.

    A query is executed by a Worker, so with none running the call doesn't fail
    fast, it waits. Measured against a real server: ~29 seconds before the SDK
    gives up retrying.
    """

    def __init__(self) -> None:
        self.queried: list = []
        self.signalled: list = []

    async def query(self, query):
        self.queried.append(query)
        await asyncio.Event().wait()  # never set, so this never returns

    async def signal(self, signal, *arguments):
        self.signalled.append((signal, arguments))


class FakeTemporal:
    """Stands in for the Temporal client, recording which order was looked up."""

    def __init__(self, current_step: str) -> None:
        self.handle = FakeWorkflowHandle(current_step)
        self.handles_asked_for: list[str] = []

    def get_workflow_handle(self, order_id: str) -> FakeWorkflowHandle:
        self.handles_asked_for.append(order_id)
        return self.handle


class FakeSupervisor:
    """Stands in for the process supervisor, recording what it was asked to do.

    Mirrors the real supervisor's three public methods. The control plane never
    needs more than these: whether a component is up, and the two ways to change
    that.
    """

    def __init__(self, down: tuple = ()) -> None:
        self.running = {name: name not in down for name in COMPONENTS}
        self.started: list[str] = []
        self.stopped: list[str] = []

    def start(self, name: str) -> int:
        self.started.append(name)
        self.running[name] = True
        return 4242  # a pid, which the control plane has no use for

    def stop(self, name: str) -> None:
        self.stopped.append(name)
        self.running[name] = False

    def is_running(self, name: str) -> bool:
        # A name it was never given reads as not running, the way the real
        # supervisor answers: it looks in the processes it actually started.
        return self.running.get(name, False)


def test_placing_an_order_goes_through_the_order_app():
    """The control plane asks the order app rather than starting the Workflow.

    Deliberate, and it carries the whole app-down lesson. Killing the order app
    has to stop new orders; if the control plane talked to Temporal directly,
    the app could be dead and the panel would keep placing orders anyway,
    teaching the opposite of the point.
    """
    order_app = FakeOrderApp(order_id="order-abc123")
    panel = TestClient(create_app(place_order=order_app.place_order))

    response = panel.post("/orders")

    assert response.status_code == 200
    assert response.json() == {"order_id": "order-abc123"}
    assert order_app.calls == 1


def test_state_reports_the_progress_of_the_order_that_was_placed():
    """The control plane remembers the order it placed, and asks that one.

    Remembering is the whole reason placing goes through here rather than
    straight from the panel to the order app: the id passes through on its way
    back, so nothing else has to be told what the current order is.
    """
    order_app = FakeOrderApp(order_id="order-abc123")
    temporal = FakeTemporal(current_step="waiting_for_kitchen")

    async def connect() -> FakeTemporal:
        return temporal

    panel = TestClient(
        create_app(
            place_order=order_app.place_order,
            connect=connect,
            supervisor=lambda: FakeSupervisor(),  # everything up, so the query runs
        )
    )

    panel.post("/orders")
    state = panel.get("/state").json()

    assert temporal.handles_asked_for == ["order-abc123"]
    assert state["order"]["id"] == "order-abc123"
    assert state["order"]["steps"] == [
        {"key": "charge", "status": "done"},
        {"key": "restaurant", "status": "done"},
        {"key": "kitchen", "status": "waiting"},
        {"key": "dispatch", "status": "upcoming"},
        {"key": "delivery", "status": "upcoming"},
    ]


def test_state_answers_promptly_when_the_progress_query_cannot_be_answered():
    """A dead Worker must not hold the panel hostage.

    Only a Worker can answer a query, so with none running the call waits
    rather than failing: ~29 seconds against a real server, because the SDK
    retries. The panel polls every 700ms, so an unbounded wait here stacks
    dozens of in-flight requests and the panel shows nothing at all while it
    happens, which is what a learner reported as the UI lagging.

    So `/state` bounds the query and answers with what it last knew, marked as
    no longer confirmed. Reporting the last known steps rather than nothing
    keeps the panel drawn; the flag is what lets it say the truth about them.
    """
    order_app = FakeOrderApp(order_id="order-abc123")
    temporal = FakeTemporal(current_step="waiting_for_kitchen")

    async def connect() -> FakeTemporal:
        return temporal

    panel = TestClient(
        create_app(
            place_order=order_app.place_order,
            connect=connect,
            supervisor=lambda: FakeSupervisor(),  # the Worker is up, just not answering
        )
    )

    panel.post("/orders")
    good = panel.get("/state").json()
    assert good["order"]["progress_confirmed"] is True

    # The query stops answering while the Worker is still up: wedged, or simply
    # slower than the bound allows.
    temporal.handle = HangingWorkflowHandle()

    started = time.monotonic()
    stale = panel.get("/state").json()
    waited = time.monotonic() - started

    assert waited < 5, f"/state waited {waited:.1f}s on an unanswerable query"
    assert stale["order"]["progress_confirmed"] is False
    assert stale["order"]["steps"] == good["order"]["steps"]  # the last it knew


def test_state_does_not_ask_at_all_when_the_worker_is_known_to_be_down():
    """With no Worker there is nobody to answer, so don't ask.

    Only a Worker executes a query, so with none running the call cannot
    succeed. It doesn't fail either, it waits, and then gives up at the
    timeout. Asking anyway spends that whole wait to learn something the
    control plane already knows, because it owns the Worker process.

    So it checks first and answers with the last progress it confirmed.
    """
    order_app = FakeOrderApp(order_id="order-abc123")
    temporal = FakeTemporal(current_step="waiting_for_kitchen")
    supervisor = FakeSupervisor()

    async def connect() -> FakeTemporal:
        return temporal

    panel = TestClient(
        create_app(
            place_order=order_app.place_order,
            connect=connect,
            supervisor=lambda: supervisor,
        )
    )

    panel.post("/orders")
    good = panel.get("/state").json()
    assert good["order"]["progress_confirmed"] is True

    # The Worker goes away. Its handle would now hang, the way a real one does.
    temporal.handle = HangingWorkflowHandle()
    panel.put("/components/worker", json={"up": False})

    stale = panel.get("/state").json()

    assert temporal.handle.queried == []  # nobody was there, so nobody was asked
    assert stale["order"]["progress_confirmed"] is False
    assert stale["order"]["steps"] == good["order"]["steps"]  # the last it knew


def test_state_reports_no_order_before_one_has_been_placed():
    """The panel asks for state the moment it loads, before anything is placed.

    There is nothing to query then, and asking anyway would send Temporal a
    lookup for an order that doesn't exist. So the absence is the answer, and
    the panel draws its opening all-upcoming state from it.
    """
    temporal = FakeTemporal(current_step="charging_payment")

    async def connect() -> FakeTemporal:
        return temporal

    panel = TestClient(create_app(place_order=FakeOrderApp().place_order, connect=connect))

    state = panel.get("/state").json()

    assert state["order"] is None
    assert temporal.handles_asked_for == []  # nothing to look up, so nothing was asked


def test_state_reports_which_components_are_running():
    """The panel's toggles have to show the truth, not what was last clicked.

    Until now the panel tracked its own switches in the browser, so a service
    that died on its own still read as up, and a reload forgot everything. The
    supervisor is the one thing that knows, so the control plane reports from it.

    This rides on `/state` rather than getting an endpoint of its own because
    the panel already polls `/state` every 700ms. A second poll would double the
    traffic to learn something the first one could have carried.

    The five names are the panel's, not the Makefile's: `app`, not `order-app`.
    The panel froze that vocabulary when it was mocked, so the backend conforms.
    """
    supervisor = FakeSupervisor(down=("payment",))
    panel = TestClient(
        create_app(place_order=FakeOrderApp().place_order, supervisor=lambda: supervisor)
    )

    state = panel.get("/state").json()

    assert state["components"] == {
        "payment": False,
        "restaurant": True,
        "dispatch": True,
        "worker": True,
        "app": True,
    }


def test_switching_a_component_off_really_stops_its_process():
    """The toggle has to stop a process, not just redraw the switch.

    This is the whole point of the demo. A learner turns off the payment
    service, and the order has to actually meet a service that isn't there. A
    toggle that only changes the picture teaches that failure is cosmetic.

    The endpoint takes the desired state rather than being a `stop` verb,
    because the panel control is a checkbox. Double-click it, or let two polls
    race, and `up: false` twice has to mean the same as once.
    """
    supervisor = FakeSupervisor()
    panel = TestClient(
        create_app(place_order=FakeOrderApp().place_order, supervisor=lambda: supervisor)
    )

    response = panel.put("/components/payment", json={"up": False})

    assert response.status_code == 200
    assert response.json() == {"name": "payment", "up": False}
    assert supervisor.stopped == ["payment"]
    assert panel.get("/state").json()["components"]["payment"] is False


def test_switching_a_component_back_on_starts_it_again():
    """Recovery is the lesson, so bringing a service back has to really start it.

    Stopping is only half the demo. While the service is down the order retries
    instead of failing, and the moment it returns the order carries on. A panel
    that can take a service down but not bring it back teaches that failure is
    permanent, which is the opposite of the point.
    """
    supervisor = FakeSupervisor(down=("payment",))
    panel = TestClient(
        create_app(place_order=FakeOrderApp().place_order, supervisor=lambda: supervisor)
    )

    response = panel.put("/components/payment", json={"up": True})

    assert response.status_code == 200
    assert response.json() == {"name": "payment", "up": True}
    assert supervisor.started == ["payment"]
    assert panel.get("/state").json()["components"]["payment"] is True


def test_asking_for_the_state_a_component_is_already_in_does_nothing():
    """A redundant toggle must not disturb a healthy process.

    This is what makes the endpoint's desired state honest. The supervisor's
    `start` clears any earlier instance before launching, so calling it on
    something already running kills it and puts a replacement in its place.
    That is invisible for a service stub and very visible for the Worker: a
    second `up: true` would bounce a Worker mid-order and stage a chaos event
    nobody asked for.

    The panel's checkbox only fires on a change, so the cases this guards are
    the ones it can't control, a reload or two requests racing.
    """
    supervisor = FakeSupervisor(down=("payment",))
    panel = TestClient(
        create_app(place_order=FakeOrderApp().place_order, supervisor=lambda: supervisor)
    )

    panel.put("/components/worker", json={"up": True})  # already up
    panel.put("/components/payment", json={"up": False})  # already down

    assert supervisor.started == []
    assert supervisor.stopped == []


def test_a_component_the_control_plane_does_not_manage_is_rejected():
    """An unknown name gets a 404, because the two wrong answers are both bad.

    `up: true` reaches into the supervisor's table of processes and throws a
    bare `KeyError`, which arrives at the panel as a 500. `up: false` is worse
    and quieter: nothing is running under that name, so the endpoint does
    nothing and reports success, telling the panel a component is down when no
    such component exists.
    """
    supervisor = FakeSupervisor()
    panel = TestClient(
        create_app(place_order=FakeOrderApp().place_order, supervisor=lambda: supervisor)
    )

    assert panel.put("/components/database", json={"up": False}).status_code == 404
    assert panel.put("/components/database", json={"up": True}).status_code == 404
    assert supervisor.started == []
    assert supervisor.stopped == []


def test_the_control_plane_launches_every_component_and_stops_them_on_the_way_out():
    """One command brings the whole demo up, and takes all of it down again.

    The supervisor can only stop what it started, so the control plane has to
    be the thing that launches everything. That is also what collapses five
    terminals into one command.

    Stopping on the way out matters just as much. Each process is launched into
    its own session precisely so it survives signals aimed at its parent, so
    nothing would clean them up otherwise. A leftover stub announces itself with
    a bind error, but a leftover Worker says nothing and keeps running orders,
    which makes the next run look fine while nothing is under control.
    """
    supervisor = FakeSupervisor(down=COMPONENTS)  # nothing launched yet

    with TestClient(
        create_app(place_order=FakeOrderApp().place_order, supervisor=lambda: supervisor)
    ) as panel:
        assert supervisor.started == list(COMPONENTS)
        assert panel.get("/state").json()["components"] == {
            name: True for name in COMPONENTS
        }

    assert supervisor.stopped == list(COMPONENTS)


def test_releasing_a_wait_signals_the_current_order():
    """The panel's two Finish buttons stand in for the kitchen and the driver.

    Nothing else sends these signals, so without them the order parks at the
    kitchen and never moves again.

    The driver's id is generated here, because the control plane is standing in
    for the driver; the Workflow only needs the signal to name whoever
    delivered it.

    The endpoints are `order_prepared` and `order_delivered` while the Workflow
    signals they send are still `kitchen_ready` and `delivered`. Deliberate, and
    temporary: the kitchen isn't what's ready, the order is, and renaming the
    signals themselves is a separate change.
    """
    order_app = FakeOrderApp(order_id="order-abc123")
    temporal = FakeTemporal(current_step="waiting_for_kitchen")

    async def connect() -> FakeTemporal:
        return temporal

    panel = TestClient(create_app(place_order=order_app.place_order, connect=connect))

    panel.post("/orders")
    prepared = panel.post("/signals/order_prepared")
    delivered = panel.post("/signals/order_delivered")

    assert prepared.status_code == 200
    assert delivered.status_code == 200

    sent = temporal.handle.signalled
    assert [signal for signal, _ in sent] == [
        OrderWorkflow.kitchen_ready,
        OrderWorkflow.delivered,
    ]

    (driver_id,) = sent[1][1]
    assert driver_id  # the delivered signal has to name a driver


def test_the_panel_is_served_by_the_control_plane():
    """The control plane serves the panel as well as answering it.

    One origin, so the panel's own fetches need no CORS and there is one thing
    to run rather than two. It also means the panel can never be pointed at a
    backend that isn't there.
    """
    panel = TestClient(create_app(place_order=FakeOrderApp().place_order))

    response = panel.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>Chaos Panel</title>" in response.text


def test_the_order_walks_from_done_through_the_current_step_to_upcoming():
    """One reported step fixes the status of all five.

    Everything the order has passed is done, everything ahead of it is
    upcoming, and the step it sits on gets the status matching what it is
    doing. The kitchen parks on a signal, so it waits.
    """
    steps = panel_steps("waiting_for_kitchen")

    assert steps == [
        {"key": "charge", "status": "done"},
        {"key": "restaurant", "status": "done"},
        {"key": "kitchen", "status": "waiting"},
        {"key": "dispatch", "status": "upcoming"},
        {"key": "delivery", "status": "upcoming"},
    ]


def test_a_step_that_calls_a_service_is_in_progress_rather_than_waiting():
    """`in-progress` and `waiting` are different states to a learner.

    A call step is doing something; a wait step is parked on someone else. The
    panel draws them differently, and `in-progress` is the word its own markup
    and stylesheet use, so that is the word the control plane has to send.
    """
    steps = panel_steps("charging_payment")

    assert steps[0] == {"key": "charge", "status": "in-progress"}


def test_a_complete_order_shows_every_step_done():
    """`complete` is the sixth key, and it names no step on the panel.

    The order has passed all five by then, so the panel draws them all done.
    Without this the query's own vocabulary would crash the translation at the
    exact moment an order finishes.
    """
    steps = panel_steps("complete")

    assert [step["status"] for step in steps] == ["done"] * 5
