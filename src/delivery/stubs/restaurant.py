"""Restaurant service stub.

A stand-in for the restaurant's order system. It accepts an order and records a
ticket, and it's idempotent on the order id: sending the same order twice records
one ticket and returns the same result. That idempotency is what lets a Workflow
retry the "send to restaurant" step after a crash without the kitchen ever
getting a duplicate ticket.

Accepting a new order takes a couple of seconds to "process", so there's a window
to kill the Worker or a dependency mid-order. The delay lives here because that's
where latency lives in reality. Tune it with RESTAURANT_DELAY_SECONDS (or the
delay_seconds argument); tests pass 0 so the suite stays fast.

The on/off switch that makes the service fail (so the step retries) arrives with
the dependency-chaos PR; for now it always succeeds.

    uv run python -m uvicorn delivery.stubs.restaurant:app --port 8082
"""

import asyncio
import os
import uuid

from fastapi import FastAPI
from pydantic import BaseModel

DEFAULT_DELAY_SECONDS = float(os.environ.get("RESTAURANT_DELAY_SECONDS", "2"))


class TicketRequest(BaseModel):
    order_id: str
    description: str = ""


class Ticket(BaseModel):
    ticket_id: str
    order_id: str
    description: str = ""


def create_app(delay_seconds: float = DEFAULT_DELAY_SECONDS) -> FastAPI:
    app = FastAPI(title="Restaurant stub")
    tickets: list[Ticket] = []

    @app.post("/tickets", response_model=Ticket)
    async def send(request: TicketRequest) -> Ticket:
        existing = next((t for t in tickets if t.order_id == request.order_id), None)
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
        return list(tickets)

    return app


app = create_app()
