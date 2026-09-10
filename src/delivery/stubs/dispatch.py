"""Dispatch service stub.

A stand-in for the delivery dispatch service. It assigns a driver to an order and
records a dispatch, and it's idempotent on the order id: dispatching the same
order twice records one dispatch and returns the same result. That idempotency is
what lets a Workflow retry the "dispatch a driver" step after a crash without ever
putting a second driver on one order.

Assigning a driver takes a couple of seconds to "process", so there's a window to
kill the Worker or a dependency mid-order. The delay lives here because that's
where latency lives in reality. Tune it with DISPATCH_DELAY_SECONDS (or the
delay_seconds argument); tests pass 0 so the suite stays fast.

The on/off switch that makes the service fail (so the step retries) arrives with
the dependency-chaos PR; for now it always succeeds.

    uv run python -m uvicorn delivery.stubs.dispatch:app --port 8083
"""

import asyncio
import os
import uuid

from fastapi import FastAPI
from pydantic import BaseModel

DEFAULT_DELAY_SECONDS = float(os.environ.get("DISPATCH_DELAY_SECONDS", "2"))


class DispatchRequest(BaseModel):
    order_id: str


class Dispatch(BaseModel):
    dispatch_id: str
    order_id: str


def create_app(delay_seconds: float = DEFAULT_DELAY_SECONDS) -> FastAPI:
    app = FastAPI(title="Dispatch stub")
    dispatches: list[Dispatch] = []

    @app.post("/dispatches", response_model=Dispatch)
    async def dispatch(request: DispatchRequest) -> Dispatch:
        existing = next((d for d in dispatches if d.order_id == request.order_id), None)
        if existing is not None:
            return existing  # idempotent: an order gets at most one dispatch
        await asyncio.sleep(delay_seconds)  # simulate assigning a driver
        record = Dispatch(
            dispatch_id=f"dsp-{uuid.uuid4().hex[:12]}",
            order_id=request.order_id,
        )
        dispatches.append(record)
        return record

    @app.get("/dispatches", response_model=list[Dispatch])
    async def get_dispatches() -> list[Dispatch]:
        return list(dispatches)

    return app


app = create_app()
