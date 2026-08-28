"""The restaurant stub creates one ticket per order, even when called repeatedly.

This idempotency mirrors payment's: sending the same order to the restaurant
twice, after a retry or a crash, records a single ticket, so the kitchen never
gets a duplicate. Each test gets a fresh app (and so a fresh ledger) from the
factory, with the accept delay turned off so the suite stays fast.
"""

from fastapi.testclient import TestClient

from delivery.stubs.restaurant import create_app


def test_send_records_one_ticket():
    client = TestClient(create_app(delay_seconds=0))

    response = client.post("/tickets", json={"order_id": "order-1", "description": "Pad Thai"})

    assert response.status_code == 200
    ticket = response.json()
    assert ticket["order_id"] == "order-1"
    assert ticket["description"] == "Pad Thai"
    assert client.get("/tickets").json() == [ticket]


def test_send_is_idempotent_on_order_id():
    client = TestClient(create_app(delay_seconds=0))
    body = {"order_id": "order-1", "description": "Pad Thai"}

    first = client.post("/tickets", json=body).json()
    second = client.post("/tickets", json=body).json()

    assert first == second  # the same ticket comes back
    assert len(client.get("/tickets").json()) == 1  # one ticket, never a duplicate
