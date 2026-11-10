"""Compaction scenarios across three compactions and every crash point.

Each witness isolates one regression of the compaction path: the base
repository passes it and the mutated repository fails it. The remaining
scenarios are the multi-phase runs — three compactions with work between
them, and a crash at each publication point — in which the regressions meet,
plus the guards that pin the segment names, the publication offset and the
no-double-apply rule so that no half of a fix can be traded for another.
"""

import pytest

from walqueue import CorruptStore, InjectedCrash, Queue, StaleLease
from walqueue.files import read_document


class CrashAt:
    def __init__(self, target):
        self.target = target

    def __call__(self, phase):
        if phase == self.target:
            raise InjectedCrash(phase)


def segments(root):
    return sorted(path.name for path in root.glob("wal-*.log"))


def pointer(root):
    return read_document(root / "CURRENT")


# ----------------------------------------------------------------- witnesses


def test_witness_01_the_next_compaction_does_not_reissue_a_segment_name(tmp_path):
    """A compaction interrupted after publication left two segments; the next one still has a name to issue."""

    queue = Queue(tmp_path)
    for index in range(3):
        queue.put(f"task-{index}", {"index": index})
        queue.compact()
    queue.put("late", {})
    before = queue.export()
    queue = Queue(tmp_path, hook=CrashAt("compact.manifest"))
    with pytest.raises(InjectedCrash):
        queue.compact()
    reopened = Queue(tmp_path)
    assert reopened.export() == before
    assert len(segments(tmp_path)) == 2
    reopened.put("later", {})
    reopened.compact()
    final = Queue(tmp_path)
    assert set(final.state.tasks) == {"task-0", "task-1", "task-2", "late", "later"}
    assert final.sequence == 5


def test_witness_02_the_write_after_a_compaction_lands_in_the_new_segment(tmp_path):
    """The compaction hands the queue over to the segment it created: one segment stays, and it is the one written to."""

    queue = Queue(tmp_path)
    queue.put("first", {})
    queue.compact()
    created = segments(tmp_path)
    assert created == ["wal-0000000000000002.log"]
    queue.put("second", {})
    assert segments(tmp_path) == created
    queue.compact()
    assert segments(tmp_path) == ["wal-0000000000000003.log"]
    assert Queue(tmp_path).export() == queue.export()


def test_witness_03_only_the_newest_segment_may_end_in_a_torn_tail(tmp_path):
    """After an interrupted compaction two segments coexist, and only the newest one holds the append point."""

    root = tmp_path / "run"
    queue = Queue(root)
    queue.put("first", {})
    queue.compact()
    queue.put("second", {})
    queue = Queue(root, hook=CrashAt("compact.rotated"))
    with pytest.raises(InjectedCrash):
        queue.compact()
    queue = Queue(root)
    sealed = sorted(path for path in queue.journal.paths if path != queue.journal.active)
    assert len(sealed) == 1
    queue.put("third", {})
    queue.journal.active.write_bytes(queue.journal.active.read_bytes()[:-3])
    reopened = Queue(root)
    assert set(reopened.state.tasks) == {"first", "second"}
    assert reopened.sequence == 2
    sealed[0].write_bytes(sealed[0].read_bytes()[:-1])
    with pytest.raises(CorruptStore):
        Queue(root)


def test_witness_04_a_compaction_that_did_not_publish_keeps_every_acknowledged_task(tmp_path):
    """A compaction interrupted before CURRENT names the snapshot may not have taken anything away."""

    queue = Queue(tmp_path)
    queue.put("first", {})
    queue.compact()
    queue.put("second", {})
    queue.put("third", {})
    before = queue.export()
    queue = Queue(tmp_path, hook=CrashAt("compact.snapshot"))
    with pytest.raises(InjectedCrash):
        queue.compact()
    reopened = Queue(tmp_path)
    assert reopened.export() == before
    reopened.put("fourth", {})
    reopened.compact()
    final = Queue(tmp_path)
    assert set(final.state.tasks) == {"first", "second", "third", "fourth"}
    assert final.sequence == 4


# ------------------------------------------------------------------- guards


def test_the_first_compaction_names_the_second_segment_and_covers_the_live_offset(tmp_path):
    """The compaction that carries the queue past offset 2 leaves it on its second segment."""

    queue = Queue(tmp_path)
    queue.put("first", {})
    queue.put("second", {})
    queue.compact()
    assert segments(tmp_path) == ["wal-0000000000000002.log"]
    assert pointer(tmp_path) == {
        "snapshot": "snapshot-0000000000000002.json",
        "through": 2,
    }
    queue.compact()
    assert segments(tmp_path) == ["wal-0000000000000003.log"]
    assert pointer(tmp_path) == {"snapshot": "snapshot-0000000000000002.json", "through": 2}
    queue.put("third", {})
    queue.compact()
    assert segments(tmp_path) == ["wal-0000000000000004.log"]
    assert pointer(tmp_path) == {"snapshot": "snapshot-0000000000000003.json", "through": 3}


def test_the_wal_holds_exactly_one_segment_after_each_of_three_compactions(tmp_path):
    queue = Queue(tmp_path)
    for index in range(3):
        queue.put(f"task-{index}", {})
        queue.compact()
        assert segments(tmp_path) == [f"wal-{index + 2:016d}.log"]
    queue.put("tail", {})
    assert Queue(tmp_path).export() == queue.export()
    assert segments(tmp_path) == ["wal-0000000000000004.log"]


def test_no_transaction_is_applied_twice_after_a_compaction_and_a_restart(tmp_path):
    queue = Queue(tmp_path)
    queue.put("task", {"value": 1}, key="key", max_attempts=5)
    (old,) = queue.reserve("worker", now=0, lease_seconds=2)
    (current,) = queue.reserve("worker", now=2, lease_seconds=20)
    queue.compact()
    queue.ack(current, now=3)
    reopened = Queue(tmp_path)
    assert reopened.inspect("task").status == "done"
    with pytest.raises(StaleLease):
        reopened.ack(old, now=4)
    reopened.compact()
    final = Queue(tmp_path)
    assert final.sequence == 5
    assert final.inspect("task").status == "done"


def test_an_interrupted_compaction_at_each_point_lets_the_next_one_finish(tmp_path):
    """Three compactions with a crash at every publication point between them, then the same queue again."""

    for index, phase in enumerate(
        ("compact.rotated", "compact.snapshot", "compact.manifest", "compact.pruned")
    ):
        root = tmp_path / f"run-{index}"
        queue = Queue(root)
        queue.put("first", {})
        queue.put("second", {})
        queue.compact()
        queue.put("late", {})
        before = queue.export()
        queue = Queue(root, hook=CrashAt(phase))
        with pytest.raises(InjectedCrash):
            queue.compact()
        reopened = Queue(root)
        assert reopened.export() == before, phase
        reopened.put("after", {})
        reopened.compact()
        final = Queue(root)
        assert set(final.state.tasks) == {"first", "second", "late", "after"}, phase
        assert final.sequence == 4, phase
        assert segments(root) == ["wal-0000000000000004.log"], phase
