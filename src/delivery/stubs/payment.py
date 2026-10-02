"""Payment service stub.

A stand-in for a real payment processor. It charges an order and records each
charge in a ledger, and it's idempotent on the order id: charging the same order
twice records one charge and returns the same result. That idempotency is what
lets a Workflow retry a charge after a crash without ever double-charging. The
ledger lives in `logs/payment-ledger.json`, so the stub remembers its charges
when the panel restarts it.

A new charge takes a couple of seconds to "process", so there's a window to kill
the Worker or a dependency mid-order. The delay lives here because that's where
latency lives in reality. Tune it with PAYMENT_DELAY_SECONDS (or the delay_seconds
argument); tests pass 0 so the suite stays fast.

The on/off switch that makes the service fail (so a step retries) arrives in a
later PR; for now it always succeeds.

    uv run python -m uvicorn delivery.stubs.payment:app --port 8081
"""

import asyncio
import os
import uuid
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

from delivery.shared import LOG_DIRECTORY
from delivery.stubs.ledger import Ledger

DEFAULT_DELAY_SECONDS = float(os.environ.get("PAYMENT_DELAY_SECONDS", "2"))


class ChargeRequest(BaseModel):
    order_id: str
    amount_cents: int


class Charge(BaseModel):
    charge_id: str
    order_id: str
    amount_cents: int


def create_app(ledger_path: Path, delay_seconds: float = DEFAULT_DELAY_SECONDS) -> FastAPI:
    app = FastAPI(title="Payment stub")
    ledger = Ledger(Charge, ledger_path)

    @app.post("/charge", response_model=Charge)
    async def charge(request: ChargeRequest) -> Charge:
        existing = ledger.find(request.order_id)
        if existing is not None:
            return existing  # idempotent: an order is charged at most once
        await asyncio.sleep(delay_seconds)  # simulate the processor working
        record = Charge(
            charge_id=f"ch-{uuid.uuid4().hex[:12]}",
            order_id=request.order_id,
            amount_cents=request.amount_cents,
        )
        ledger.append(record)
        return record

    @app.get("/ledger", response_model=list[Charge])
    async def get_ledger() -> list[Charge]:
        return ledger.records()

    return app


app = create_app(ledger_path=LOG_DIRECTORY / "payment-ledger.json")
