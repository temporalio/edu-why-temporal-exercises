"""A stub's record of what it has done, kept on disk.

The panel stops and starts the stubs, and a stub's idempotency depends on its
ledger outliving those restarts, the way a real service's records do. The
ledger writes every record to its file and reads them back on startup.

Each write goes to a temporary file that then replaces the ledger, so a stub
killed mid-write leaves the previous ledger intact rather than a half-written
one.
"""

import json
from pathlib import Path
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

Record = TypeVar("Record", bound=BaseModel)


class Ledger(Generic[Record]):
    """The records a stub has made, one per order.

    Every record type carries an `order_id`, which is what each stub's
    idempotency is keyed on.
    """

    def __init__(self, record_type: type[Record], path: Path) -> None:
        self._record_type = record_type
        self._path = path
        self._records: list[Record] = self._load()

    def find(self, order_id: str) -> Optional[Record]:
        """The record for this order, or None if the order has none yet."""
        for record in self._records:
            if record.order_id == order_id:
                return record

        return None

    def append(self, record: Record) -> None:
        """Add a record, writing it to disk first.

        The record joins the ledger in memory only once the write succeeds, so
        a failed write leaves memory and disk agreeing.
        """
        updated = [*self._records, record]
        self._save(updated)
        self._records = updated

    def records(self) -> list[Record]:
        return list(self._records)

    def _load(self) -> list[Record]:
        if not self._path.exists():
            return []

        entries = json.loads(self._path.read_text())

        return [self._record_type.model_validate(entry) for entry in entries]

    def _save(self, records: list[Record]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

        entries = [record.model_dump() for record in records]
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(entries, indent=2))
        temporary.replace(self._path)
