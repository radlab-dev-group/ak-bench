import pytest
from walqueue import KeyConflict, Queue, StaleLease


def test_live_put_lease_ack_and_idempotency(tmp_path):
    queue = Queue(tmp_path)
    queue.put("first", {"amount": 7})
    (token,) = queue.reserve("worker", now=0, lease_seconds=10)
    queue.ack(token, now=3)
    queue.put("first", {"amount": 7})
    assert queue.stats() == {"ready": 0, "leased": 0, "done": 1, "dead": 0}
    with pytest.raises(KeyConflict):
        queue.put("first", {"amount": 8})


def test_live_expiration_fences_old_worker(tmp_path):
    queue = Queue(tmp_path)
    queue.put("task", {})
    (old,) = queue.reserve("worker", now=0, lease_seconds=5)
    (new,) = queue.reserve("worker", now=5, lease_seconds=5)
    assert new.generation == old.generation + 1
    with pytest.raises(StaleLease):
        queue.ack(old, now=6)
    queue.ack(new, now=6)


def test_simple_restart_replays_put(tmp_path):
    Queue(tmp_path).put("one", {"nested": [1, 2]})
    queue = Queue(tmp_path)
    assert queue.inspect("one").payload == {"nested": [1, 2]}
    assert queue.stats()["ready"] == 1


def test_batch_validation_is_atomic(tmp_path):
    queue = Queue(tmp_path)
    with pytest.raises(KeyConflict):
        queue.put_many(
            [
                {
                    "task_id": "one",
                    "key": "key",
                    "payload": {},
                    "available_at": 0,
                    "max_attempts": 3,
                },
                {
                    "task_id": "two",
                    "key": "key",
                    "payload": {},
                    "available_at": 0,
                    "max_attempts": 3,
                },
            ]
        )
    assert queue.export()["sequence"] == 0
    assert queue.stats()["ready"] == 0


def test_live_release_and_dead_letter(tmp_path):
    queue = Queue(tmp_path)
    queue.put("once", {}, max_attempts=1)
    (token,) = queue.reserve("worker", now=0, lease_seconds=10)
    queue.release(token, now=1, delay=4)
    assert queue.inspect("once").status == "dead"
