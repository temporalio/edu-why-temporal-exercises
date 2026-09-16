"""The control plane turns what the Workflow knows into what the panel draws.

The Workflow answers a progress query with one of six keys naming where the
order has got to. The panel needs something different: every step, each with a
status it can render. Nothing else in the system does that translation, and it
is not a detail, because two of the panel's five statuses are not in the
Workflow's vocabulary at all. `waiting` distinguishes the two steps that park on
a signal from the three that call a service, and `retrying` is inferred from a
stopped service, since the Workflow only knows it is awaiting an Activity, not
that the Activity keeps failing.

`retrying` doesn't appear yet. It needs the supervisor to report a stopped
service, and until the control plane owns those processes every service is
assumed to be up.
"""

from fastapi.testclient import TestClient

from delivery.control_plane import create_app, panel_steps
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


class FakeTemporal:
    """Stands in for the Temporal client, recording which order was looked up."""

    def __init__(self, current_step: str) -> None:
        self.handle = FakeWorkflowHandle(current_step)
        self.handles_asked_for: list[str] = []

    def get_workflow_handle(self, order_id: str) -> FakeWorkflowHandle:
        self.handles_asked_for.append(order_id)
        return self.handle


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

    panel = TestClient(create_app(place_order=order_app.place_order, connect=connect))

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


def test_releasing_a_wait_signals_the_current_order():
    """The panel's two Finish buttons stand in for the kitchen and the driver.

    Nothing else signals an order placed from the panel. The timed versions in
    `starter.py` are a convenience for running by hand, so without these the
    order parks at the kitchen and never moves again.

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
