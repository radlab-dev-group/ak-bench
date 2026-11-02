import pytest
from walqueue import Queue, StaleLease


def test_compaction_preserves_a_completed_task_and_key(tmp_path):
    queue = Queue(tmp_path)
    queue.put("invoice", {"amount": 7}, key="request")
    (lease,) = queue.reserve("worker", now=0, lease_seconds=10)
    queue.ack(lease, now=1)
    queue.compact()
    queue = Queue(tmp_path)
    queue.put("invoice", {"amount": 7}, key="request")
    assert queue.inspect("invoice").status == "done"
    assert queue.reserve("worker", now=2, lease_seconds=10) == []


def test_old_generation_stays_stale_after_snapshot_and_restart(tmp_path):
    queue = Queue(tmp_path)
    queue.put("task", {})
    (old,) = queue.reserve("worker", now=0, lease_seconds=5)
    (current,) = queue.reserve("worker", now=5, lease_seconds=10)
    queue.compact()
    queue = Queue(tmp_path)
    with pytest.raises(StaleLease):
        queue.ack(old, now=6)
    queue.ack(current, now=6)
