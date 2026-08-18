"""The payment stub charges once per order, even when called repeatedly.

That idempotency is the foundation of the demo's headline: a charge can be
retried after a crash and the customer is still charged exactly once. Each test
gets a fresh app (and so a fresh ledger) from the factory, with the processing
delay turned off so the suite stays fast.
"""

from fastapi.testclient import TestClient

from delivery.stubs.payment import create_app


def test_charge_records_one_charge():
    client = TestClient(create_app(delay_seconds=0))

    response = client.post("/charge", json={"order_id": "order-1", "amount_cents": 1999})

    assert response.status_code == 200
    charge = response.json()
    assert charge["order_id"] == "order-1"
    assert charge["amount_cents"] == 1999
    assert client.get("/ledger").json() == [charge]


def test_charge_is_idempotent_on_order_id():
    client = TestClient(create_app(delay_seconds=0))
    body = {"order_id": "order-1", "amount_cents": 1999}

    first = client.post("/charge", json=body).json()
    second = client.post("/charge", json=body).json()

    assert first == second  # the same charge comes back
    assert len(client.get("/ledger").json()) == 1  # charged exactly once
