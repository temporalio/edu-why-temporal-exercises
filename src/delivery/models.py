"""Domain types passed between the client, the Workflow, and its Activities.

Plain dataclasses so Temporal's default data converter can serialize them.
Amounts are in integer cents, the same representation real payment processors
use, so there's never a fractional-rounding question.
"""

from dataclasses import dataclass


@dataclass
class Order:
    order_id: str
    amount_cents: int
    description: str = ""
