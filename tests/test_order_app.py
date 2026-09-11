"""The order app is the demo's front door: it takes a request and starts an order.

Placing an order is the whole of its job. It doesn't wait for the order to
finish, because the Workflow outlives the request, which is the point of the
app-down toggle: kill this service and no new orders can be placed, while
anything already running carries on without it.

Temporal is faked here through the injected `connect`, so these tests check what
the app asks Temporal to do rather than standing up a server.
"""

from fastapi.testclient import TestClient

from delivery.order_app import create_app
from delivery.shared import TASK_QUEUE
from delivery.workflows import OrderWorkflow


class FakeClient:
    """Records the Workflows it was asked to start."""

    def __init__(self) -> None:
        self.started: list[dict] = []

    async def start_workflow(self, workflow, order, *, id, task_queue):
        self.started.append(
            {"workflow": workflow, "order": order, "id": id, "task_queue": task_queue}
        )


def an_app(fake: FakeClient) -> TestClient:
    async def connect() -> FakeClient:
        return fake

    return TestClient(create_app(connect=connect))


def test_placing_an_order_starts_the_order_workflow():
    fake = FakeClient()
    client = an_app(fake)

    response = client.post("/orders")

    assert response.status_code == 200
    order_id = response.json()["order_id"]

    assert len(fake.started) == 1
    started = fake.started[0]
    assert started["workflow"] is OrderWorkflow.run
    assert started["task_queue"] == TASK_QUEUE
    assert started["id"] == order_id  # the Workflow id is the order id
    assert started["order"].order_id == order_id


def test_each_order_gets_its_own_id():
    """Two orders are two Workflows, not one reused id.

    Nothing here enforces one-order-at-a-time; the panel disables its button
    while an order is running. So the app has to stay safe to call twice.
    """
    fake = FakeClient()
    client = an_app(fake)

    first = client.post("/orders").json()["order_id"]
    second = client.post("/orders").json()["order_id"]

    assert first != second
    assert [started["id"] for started in fake.started] == [first, second]
