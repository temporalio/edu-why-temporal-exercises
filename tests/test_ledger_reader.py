"""The control plane counts an order's records by asking the stubs themselves.

The reader is what turns each stub's ledger into the count the panel shows, so
it's tested against the real stub apps, served in memory through an httpx
transport. Each ledger is written directly with a duplicate in it, which the
stubs' idempotency can no longer produce through their API, to check that the
reader counts what the service holds rather than assuming one.
"""

import asyncio

import httpx
import pytest

from delivery.control_plane import ledger_reader
from delivery.stubs import dispatch, payment, restaurant
from delivery.stubs.ledger import Ledger

STUBS = [
    ("payment", payment, payment.Charge, {"charge_id": "ch-1", "amount_cents": 1999}),
    ("restaurant", restaurant, restaurant.Ticket, {"ticket_id": "tkt-1"}),
    ("dispatch", dispatch, dispatch.Dispatch, {"dispatch_id": "dsp-1"}),
]


@pytest.mark.parametrize("service, module, record_type, fields", STUBS)
def test_the_reader_counts_only_the_orders_own_records(tmp_path, service, module, record_type, fields):
    ledger_path = tmp_path / f"{service}-ledger.json"
    ledger = Ledger(record_type, ledger_path)
    ledger.append(record_type(order_id="order-1", **fields))
    ledger.append(record_type(order_id="order-1", **fields))  # the duplicate
    ledger.append(record_type(order_id="order-2", **fields))

    stub = module.create_app(ledger_path=ledger_path, delay_seconds=0)
    count_records = ledger_reader(transport=httpx.ASGITransport(app=stub))

    assert asyncio.run(count_records(service, "order-1")) == 2
    assert asyncio.run(count_records(service, "order-2")) == 1


def test_a_service_that_cannot_be_reached_has_an_unknown_count():
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    count_records = ledger_reader(transport=httpx.MockTransport(refuse))

    assert asyncio.run(count_records("payment", "order-1")) is None
