"""Symptom-level checks for walqueue-compaction-002.

These are the complaints as the operators phrased them. They say what the
store did; they do not say where.
"""

import pytest

from walqueue import InjectedCrash, Queue


class CrashAt:
    def __init__(self, target):
        self.target = target

    def __call__(self, phase):
        if phase == self.target:
            raise InjectedCrash(phase)


def test_the_second_compaction_of_a_run_does_not_die(tmp_path):
    queue = Queue(tmp_path)
    for index in range(3):
        queue.put(f"task-{index}", {})
        queue.compact()
    queue.put("late", {})
    queue.compact()
    assert set(Queue(tmp_path).state.tasks) == {"task-0", "task-1", "task-2", "late"}


def test_a_run_of_compactions_does_not_grow_a_wal_file_per_compaction(tmp_path):
    queue = Queue(tmp_path)
    for index in range(4):
        queue.put(f"task-{index}", {})
        queue.compact()
        queue.put(f"other-{index}", {})
    assert len(list(tmp_path.glob("wal-*.log"))) == 1
    assert set(Queue(tmp_path).state.tasks) == {
        name
        for index in range(4)
        for name in (f"task-{index}", f"other-{index}")
    }


def test_an_interrupted_compaction_then_an_interrupted_write_stays_openable(tmp_path):
    queue = Queue(tmp_path)
    queue.put("first", {})
    queue.compact()
    queue.put("second", {})
    queue = Queue(tmp_path, hook=CrashAt("compact.rotated"))
    with pytest.raises(InjectedCrash):
        queue.compact()
    queue = Queue(tmp_path)
    queue.put("third", {})
    reopened = Queue(tmp_path)
    assert set(reopened.state.tasks) in ({"first", "second"}, {"first", "second", "third"})
    assert reopened.sequence in (2, 3)


def test_an_interrupted_compaction_does_not_lose_acknowledged_work(tmp_path):
    queue = Queue(tmp_path)
    queue.put("first", {})
    queue.compact()
    queue.put("second", {})
    queue.put("third", {})
    before = queue.export()
    queue = Queue(tmp_path, hook=CrashAt("compact.snapshot"))
    with pytest.raises(InjectedCrash):
        queue.compact()
    assert Queue(tmp_path).export() == before
    queue = Queue(tmp_path)
    queue.put("fourth", {})
    queue.compact()
    assert set(Queue(tmp_path).state.tasks) == {"first", "second", "third", "fourth"}
