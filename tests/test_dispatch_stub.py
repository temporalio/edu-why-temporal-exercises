"""The dispatch stub creates one dispatch per order, even when called repeatedly.

This idempotency mirrors the restaurant's and payment's: dispatching a driver for
the same order twice, after a retry or a crash, records a single dispatch, so a
recovered Worker never puts a second driver on one order. Each test gets a fresh
app (and so a fresh ledger) from the factory, with the accept delay turned off so
the suite stays fast.
"""

from fastapi.testclient import TestClient

from delivery.stubs.dispatch import create_app


def test_dispatch_records_one_dispatch():
    client = TestClient(create_app(delay_seconds=0))

    response = client.post("/dispatches", json={"order_id": "order-1"})

    assert response.status_code == 200
    dispatch = response.json()
    assert dispatch["order_id"] == "order-1"
    assert dispatch["dispatch_id"]
    assert client.get("/dispatches").json() == [dispatch]


def test_dispatch_is_idempotent_on_order_id():
    client = TestClient(create_app(delay_seconds=0))
    body = {"order_id": "order-1"}

    first = client.post("/dispatches", json=body).json()
    second = client.post("/dispatches", json=body).json()

    assert first == second  # the same dispatch comes back
    assert len(client.get("/dispatches").json()) == 1  # one dispatch, never a duplicate
