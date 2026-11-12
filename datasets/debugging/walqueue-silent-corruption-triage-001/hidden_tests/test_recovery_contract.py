"""The half of the rule that must survive the fix.

Refusing a damaged sealed segment is only half of ADR-0003; the other half is
that a torn tail in the segment the journal appends to stays a recoverable
truncation, and that running out of space in the middle of a write is an
interruption rather than a corruption. A fix that turns every incomplete frame
into an error passes the ticket and breaks these.
"""

from __future__ import annotations

import errno
import subprocess
import sys
from pathlib import Path

import pytest

TORN_TAIL = b"\x00\x00\x01\x00"


def _workspace() -> Path:
    for candidate in (Path.cwd(), *Path(__file__).resolve().parents):
        if (candidate / "src" / "walqueue").is_dir():
            return candidate
    raise RuntimeError("hidden tests run inside a prepared walqueue workspace")


def _store_crashed_in_compaction(root: Path):
    from walqueue import InjectedCrash, Queue

    def hook(point: str) -> None:
        if point == "compact.rotated":
            raise InjectedCrash(point)

    queue = Queue(root, hook=hook)
    queue.put("inv-1", {"cents": 100})
    queue.put("inv-2", {"cents": 200})
    try:
        queue.compact()
    except InjectedCrash:
        pass
    return queue


def test_a_torn_tail_in_the_append_target_is_repaired_once(tmp_path):
    from walqueue import Queue

    store = tmp_path / "store"
    _store_crashed_in_compaction(store)
    sealed, newest = sorted(store.glob("wal-*.log"))
    sealed_before = sealed.read_bytes()
    newest.write_bytes(newest.read_bytes() + TORN_TAIL)

    assert Queue(store).export()["sequence"] == 2
    assert newest.read_bytes() == b"", (
        "the torn tail was not truncated; it is repaired once and then forgotten"
    )
    assert sealed.read_bytes() == sealed_before
    assert Queue(store).export()["sequence"] == 2


def test_the_repaired_store_goes_on_accepting_work(tmp_path):
    from walqueue import Queue

    store = tmp_path / "store"
    _store_crashed_in_compaction(store)
    segments = sorted(store.glob("wal-*.log"))
    segments[-1].write_bytes(segments[-1].read_bytes() + TORN_TAIL)
    queue = Queue(store)
    queue.put("inv-3", {"cents": 300})
    assert Queue(store).export()["sequence"] == 3
    assert Queue(store).inspect("inv-3").status == "ready"


def test_running_out_of_space_mid_write_loses_nothing_and_leaves_nothing(tmp_path):
    from walqueue import Queue

    store = tmp_path / "store"
    queue = Queue(store)
    queue.put("inv-1", {"cents": 100})
    queue.put("inv-2", {"cents": 200})
    confirmed = queue.export()

    def enospc(point: str) -> None:
        if point == "append.payload":
            raise OSError(errno.ENOSPC, "No space left on device")

    broken = Queue(store, hook=enospc)
    with pytest.raises(OSError):
        broken.put("inv-3", {"cents": 300})

    reopened = Queue(store)
    assert reopened.export() == confirmed, (
        "an interrupted write must leave exactly the state that was confirmed"
    )


def test_a_crash_after_the_frame_is_on_disk_is_a_committed_transaction(tmp_path):
    from walqueue import InjectedCrash, Queue

    store = tmp_path / "store"

    def hook(point: str) -> None:
        if point == "compact.rotated":
            raise InjectedCrash(point)

    queue = Queue(store, hook=hook)
    queue.put("inv-1", {"cents": 100})
    queue.put("inv-2", {"cents": 200})
    expected = queue.export()
    try:
        queue.compact()
    except InjectedCrash:
        pass
    assert Queue(store).export() == expected


def test_the_repository_suite_still_passes():
    root = _workspace()
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
