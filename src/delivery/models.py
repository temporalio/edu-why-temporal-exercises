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


@dataclass
class OrderResult:
    """What OrderWorkflow returns once the order completes.

    A structured result rather than a bare id, so later steps can add fields
    (delivery confirmation) without changing the Workflow's return signature.
    Evolving a Workflow's contract by adding fields to a struct, rather than
    changing positional types, is the Temporal-friendly way to keep older and
    newer versions compatible.
    """

    order_id: str
    charge_id: str
    ticket_id: str
    dispatch_id: str
