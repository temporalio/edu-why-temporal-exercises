"""Restaurant service stub.

A stand-in for the restaurant's order system. It accepts an order and records a
ticket, and it's idempotent on the order id: sending the same order twice records
one ticket and returns the same result. That idempotency is what lets a Workflow
retry the "send to restaurant" step after a crash without the kitchen ever
getting a duplicate ticket. The tickets live in `logs/restaurant-ledger.json`,
so the stub remembers them when the panel restarts it.

Accepting a new order takes a couple of seconds to "process", so there's a window
to kill the Worker or a dependency mid-order. The delay lives here because that's
where latency lives in reality. Tune it with RESTAURANT_DELAY_SECONDS (or the
delay_seconds argument); tests pass 0 so the suite stays fast.

    uv run python -m uvicorn delivery.stubs.restaurant:app --port 8082
"""

import asyncio
import os
import uuid
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

from delivery.shared import LOG_DIRECTORY
from delivery.stubs.ledger import Ledger

DEFAULT_DELAY_SECONDS = float(os.environ.get("RESTAURANT_DELAY_SECONDS", "2"))


class TicketRequest(BaseModel):
    order_id: str
    description: str = ""


class Ticket(BaseModel):
    ticket_id: str
    order_id: str
    description: str = ""


def create_app(ledger_path: Path, delay_seconds: float = DEFAULT_DELAY_SECONDS) -> FastAPI:
    app = FastAPI(title="Restaurant stub")
    tickets = Ledger(Ticket, ledger_path)

    @app.post("/tickets", response_model=Ticket)
    async def send(request: TicketRequest) -> Ticket:
        existing = tickets.find(request.order_id)
        if existing is not None:
            return existing  # idempotent: an order becomes at most one ticket
        await asyncio.sleep(delay_seconds)  # simulate the restaurant accepting it
        record = Ticket(
            ticket_id=f"tkt-{uuid.uuid4().hex[:12]}",
            order_id=request.order_id,
            description=request.description,
        )
        tickets.append(record)
        return record

    @app.get("/tickets", response_model=list[Ticket])
    async def get_tickets() -> list[Ticket]:
        return tickets.records()

    return app


app = create_app(ledger_path=LOG_DIRECTORY / "restaurant-ledger.json")
