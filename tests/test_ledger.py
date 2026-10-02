"""A stub's ledger remembers every record, across restarts.

The stubs' idempotency rests on this: a stub only recognizes an order it has
already handled if its ledger still holds the record. The panel restarts stubs
on demand, so the ledger has to outlive the process that wrote it, and a write
cut short has to leave the earlier records intact. Each test gets its own
ledger file in a temporary directory.
"""

from pathlib import Path

import pytest
from pydantic import BaseModel

from delivery.stubs.ledger import Ledger


class Entry(BaseModel):
    order_id: str
    note: str = ""


def test_a_recorded_order_can_be_found_by_its_order_id(tmp_path):
    ledger = Ledger(Entry, tmp_path / "ledger.json")

    ledger.append(Entry(order_id="order-1", note="first"))

    assert ledger.find("order-1") == Entry(order_id="order-1", note="first")


def test_an_order_with_no_record_is_not_found(tmp_path):
    ledger = Ledger(Entry, tmp_path / "ledger.json")

    ledger.append(Entry(order_id="order-1"))

    assert ledger.find("order-2") is None


def test_the_ledger_lists_every_record_in_the_order_they_were_made(tmp_path):
    ledger = Ledger(Entry, tmp_path / "ledger.json")

    ledger.append(Entry(order_id="order-1"))
    ledger.append(Entry(order_id="order-2"))

    assert ledger.records() == [Entry(order_id="order-1"), Entry(order_id="order-2")]


def test_records_survive_a_restart(tmp_path):
    path = tmp_path / "ledger.json"

    Ledger(Entry, path).append(Entry(order_id="order-1", note="first"))
    restarted = Ledger(Entry, path)

    assert restarted.find("order-1") == Entry(order_id="order-1", note="first")
    assert restarted.records() == [Entry(order_id="order-1", note="first")]


def test_a_ledger_whose_file_does_not_exist_yet_starts_empty(tmp_path):
    ledger = Ledger(Entry, tmp_path / "ledger.json")

    assert ledger.records() == []


def test_a_write_cut_short_leaves_the_earlier_records_intact(tmp_path, monkeypatch):
    """Stand-in for a stub killed mid-write.

    The final step of a write replaces the ledger file with the newly written
    one. Making that step fail leaves the write half done, which is the moment a
    `kill -9` could land. The ledger on disk should still be the previous one,
    whole.
    """
    path = tmp_path / "ledger.json"
    ledger = Ledger(Entry, path)
    ledger.append(Entry(order_id="order-1"))

    def fail_to_replace(self, target):
        raise OSError("killed mid-write")

    monkeypatch.setattr(Path, "replace", fail_to_replace)
    with pytest.raises(OSError):
        ledger.append(Entry(order_id="order-2"))
    monkeypatch.undo()

    assert Ledger(Entry, path).records() == [Entry(order_id="order-1")]


def test_a_write_that_fails_is_not_recorded_in_memory_either(tmp_path, monkeypatch):
    """A record the ledger couldn't write isn't one it holds.

    Otherwise the stub would treat the order as handled while its file says it
    isn't, and the two would disagree until the next restart.
    """
    ledger = Ledger(Entry, tmp_path / "ledger.json")
    ledger.append(Entry(order_id="order-1"))

    def fail_to_replace(self, target):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", fail_to_replace)
    with pytest.raises(OSError):
        ledger.append(Entry(order_id="order-2"))
    monkeypatch.undo()

    assert ledger.find("order-2") is None
    assert ledger.records() == [Entry(order_id="order-1")]
