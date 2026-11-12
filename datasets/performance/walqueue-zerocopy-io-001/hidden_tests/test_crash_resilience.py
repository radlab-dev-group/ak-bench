"""The half that stops `fsync` from being the thing that was optimised.

Every hook point in the journal and the compaction path, a crash at each one,
and one question afterwards: is what the client was told still there, and is
nothing it was not told about now there? `ADR-0004` is the contract; this is the
acceptance test for it.
"""

from __future__ import annotations

import pytest

from walqueue import InjectedCrash, Queue

HOOKS = (
    "append.header",
    "append.payload",
    "append.frame",
    "append.synced",
    "compact.rotated",
    "compact.snapshot",
    "compact.manifest",
    "compact.pruned",
)


class CrashAt:
    def __init__(self, target: str):
        self.target = target

    def __call__(self, phase: str) -> None:
        if phase == self.target:
            raise InjectedCrash(phase)


def _settled(tmp_path):
    """A queue with confirmed work in it, and the export the client was owed."""

    queue = Queue(tmp_path)
    for index in range(6):
        queue.put(f"task-{index}", {"n": index})
    (lease,) = queue.reserve("worker", now=0, lease_seconds=10)
    queue.ack(lease, now=1)
    queue.compact()
    for index in range(6, 10):
        queue.put(f"task-{index}", {"n": index})
    return queue, queue.export()


@pytest.mark.parametrize("hook", HOOKS)
def test_a_crash_at_a_hook_loses_nothing_that_was_confirmed(tmp_path, hook: str):
    queue, owed = _settled(tmp_path)
    queue.hook = CrashAt(hook)
    with pytest.raises(InjectedCrash):
        queue.put("after-the-crash", {"n": 99})
    recovered = Queue(tmp_path)
    assert recovered.export() == owed, (
        f"reopening after a crash at {hook!r} did not return to the confirmed state"
    )
    assert "after-the-crash" not in recovered.export()["state"]["tasks"], (
        f"a crash at {hook!r} left a record behind that was never acknowledged"
    )


@pytest.mark.parametrize("hook", HOOKS)
def test_the_store_still_works_after_a_crash_at_a_hook(tmp_path, hook: str):
    queue, owed = _settled(tmp_path)
    queue.hook = CrashAt(hook)
    with pytest.raises(InjectedCrash):
        queue.put("never", {"n": 0})

    recovered = Queue(tmp_path)
    recovered.put("fresh", {"n": 100})
    (lease,) = recovered.reserve("worker", now=50, lease_seconds=5)
    recovered.ack(lease, now=51)
    assert recovered.stats()["done"] == 2
    assert recovered.export()["state"]["tasks"][-1]["task_id"] == "fresh"
    assert Queue(tmp_path).export() == recovered.export()


def test_the_frame_format_is_the_one_the_codec_reads(tmp_path):
    """A store written by the candidate still decodes under the seed's rules."""

    queue, _owed = _settled(tmp_path)
    del queue
    from walqueue.codec import decode

    segments = sorted((tmp_path).glob("wal-*.log"))
    assert segments, "the queue wrote no segment at all"
    for path in segments:
        decoded = decode(path.read_bytes(), allow_torn_tail=path == segments[-1])
        for document in decoded.documents:
            assert isinstance(document.get("sequence"), int)
            assert isinstance(document.get("commands"), list) and document["commands"]


def test_the_seed_checksum_still_rejects_a_changed_payload(tmp_path):
    """Speed may not quietly change what the digest covers."""

    queue = Queue(tmp_path)
    queue.put("one", {"n": 1})
    segments = sorted(tmp_path.glob("wal-*.log"))
    path = segments[-1]
    data = bytearray(path.read_bytes())
    data[-1] ^= 0x01
    path.write_bytes(bytes(data))

    with pytest.raises(Exception) as caught:
        Queue(tmp_path)
    assert type(caught.value).__name__ == "CorruptStore"
