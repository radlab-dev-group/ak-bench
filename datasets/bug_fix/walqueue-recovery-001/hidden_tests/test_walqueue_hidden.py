"""Crash matrices, storage integrity, fencing, and an independent queue oracle."""

import json
import os
import random
import subprocess
import sys
from copy import deepcopy

import pytest
from walqueue import CorruptStore, InjectedCrash, KeyConflict, Queue, StaleLease
from walqueue.codec import encode
from walqueue.files import read_document, write_document


class CrashAt:
    def __init__(self, target):
        self.target = target

    def __call__(self, phase):
        if phase == self.target:
            raise InjectedCrash(phase)


def populated(path):
    queue = Queue(path)
    queue.put("done", {"value": 1}, key="done-key")
    (completed,) = queue.reserve("same-worker", now=0, lease_seconds=5)
    queue.ack(completed, now=1)
    queue.put("dead", {"value": 2}, max_attempts=1)
    (exhausted,) = queue.reserve("same-worker", now=1, lease_seconds=2)
    queue.release(exhausted, now=2)
    queue.put("leased", {"value": 3}, max_attempts=5)
    (old,) = queue.reserve("same-worker", now=2, lease_seconds=2)
    (current,) = queue.reserve("same-worker", now=4, lease_seconds=20)
    queue.put("ready", {"value": 4}, available_at=30)
    return queue, old, current


@pytest.mark.parametrize(
    "phase", ["compact.rotated", "compact.snapshot", "compact.manifest", "compact.pruned"]
)
def test_compaction_crash_matrix_preserves_complete_state(phase, tmp_path):
    queue, old, current = populated(tmp_path)
    before = queue.export()
    queue = Queue(tmp_path, hook=CrashAt(phase))
    with pytest.raises(InjectedCrash):
        queue.compact()
    queue = Queue(tmp_path)
    assert queue.export() == before
    assert Queue(tmp_path).export() == before
    with pytest.raises(StaleLease):
        queue.ack(old, now=5)
    queue.ack(current, now=5)
    queue.put("done", {"value": 1}, key="done-key")
    assert queue.inspect("done").status == "done"
    assert queue.inspect("dead").status == "dead"
    assert Queue(tmp_path).export() == queue.export()


@pytest.mark.parametrize(
    "phase,committed",
    [
        ("append.header", False),
        ("append.payload", False),
        ("append.frame", True),
        ("append.synced", True),
    ],
)
@pytest.mark.parametrize("compacted", [False, True])
def test_interrupted_batch_is_atomic_and_tail_repair_survives_second_restart(
    phase, committed, compacted, tmp_path
):
    queue = Queue(tmp_path)
    queue.put("before", {"value": 0})
    if compacted:
        queue.compact()
    queue.put("prefix", {"value": 1})
    queue = Queue(tmp_path, hook=CrashAt(phase))
    with pytest.raises(InjectedCrash):
        queue.put_many(
            [
                {
                    "task_id": "left",
                    "key": "left",
                    "payload": {},
                    "available_at": 0,
                    "max_attempts": 3,
                },
                {
                    "task_id": "right",
                    "key": "right",
                    "payload": {},
                    "available_at": 0,
                    "max_attempts": 3,
                },
            ]
        )
    queue = Queue(tmp_path)
    expected = {"before", "prefix"} | ({"left", "right"} if committed else set())
    assert set(queue.state.tasks) == expected
    assert set(Queue(tmp_path).state.tasks) == expected
    queue.put("after", {"value": 2})
    reopened = Queue(tmp_path)
    assert set(reopened.state.tasks) == expected | {"after"}
    reopened.compact()
    assert Queue(tmp_path).export() == reopened.export()


@pytest.mark.parametrize("operation", ["put", "lease", "ack", "release", "expire"])
def test_first_transaction_after_snapshot_is_never_skipped(operation, tmp_path):
    queue = Queue(tmp_path)
    queue.put("task", {}, max_attempts=4)
    token = None
    if operation in {"ack", "release", "expire"}:
        (token,) = queue.reserve("worker", now=0, lease_seconds=5)
    queue.compact()
    if operation == "put":
        queue.put("suffix", {})
    elif operation == "lease":
        queue.reserve("worker", now=0, lease_seconds=5)
    elif operation == "ack":
        queue.ack(token, now=1)
    elif operation == "release":
        queue.release(token, now=1, delay=7)
    else:
        queue.reap(5)
    assert Queue(tmp_path).export() == queue.export()
    assert Queue(tmp_path).export() == queue.export()


def test_old_segments_left_after_publication_are_not_replayed_twice(tmp_path):
    queue = Queue(tmp_path)
    queue.put("task", {})
    (token,) = queue.reserve("worker", now=0, lease_seconds=20)
    queue = Queue(tmp_path, hook=CrashAt("compact.manifest"))
    with pytest.raises(InjectedCrash):
        queue.compact()
    assert len(list(tmp_path.glob("wal-*.log"))) == 2
    reopened = Queue(tmp_path)
    assert reopened.inspect("task").attempts == 1
    reopened.ack(token, now=2)
    reopened.compact()
    assert Queue(tmp_path).inspect("task").status == "done"


def test_unpublished_orphan_is_not_a_recovery_authority(tmp_path):
    queue = Queue(tmp_path)
    queue.put("published", {})
    queue.compact()
    queue.put("suffix", {})
    before = queue.export()
    orphan = tmp_path / "snapshot-0000000000000999.json"
    write_document(orphan, {"version": 1, "through": 999, "state": {"tasks": [], "keys": {}}})
    assert Queue(tmp_path).export() == before
    orphan.write_bytes(b"interrupted orphan snapshot")
    assert Queue(tmp_path).export() == before


def test_snapshot_without_current_never_hides_the_wal(tmp_path):
    queue = Queue(tmp_path)
    queue.put("durable", {})
    write_document(
        tmp_path / "snapshot-0000000000000099.json",
        {"version": 1, "through": 99, "state": {"tasks": [], "keys": {}}},
    )
    assert Queue(tmp_path).export() == queue.export()


def test_generation_and_original_idempotency_survive_many_compactions(tmp_path):
    queue = Queue(tmp_path)
    queue.put("task", {"request": [1, 2]}, key="original", available_at=2, max_attempts=5)
    old_tokens = []
    now = 2
    for generation in range(1, 5):
        (token,) = queue.reserve("same-worker", now=now, lease_seconds=10)
        assert token.generation == generation
        queue.compact()
        queue = Queue(tmp_path)
        before = queue.export()
        for old in old_tokens:
            with pytest.raises(StaleLease):
                queue.ack(old, now=now + 1)
        assert queue.export() == before
        if generation < 4:
            queue.release(token, now=now + 1, delay=2)
        else:
            queue.ack(token, now=now + 1)
        old_tokens.append(token)
        now += 3
        queue.compact()
        queue = Queue(tmp_path)
    queue.put("task", {"request": [1, 2]}, key="original", available_at=2, max_attempts=5)
    assert queue.inspect("task").status == "done"
    with pytest.raises(KeyConflict):
        queue.put("other", {}, key="original")


def test_ack_at_exact_deadline_rejected_without_persistent_changes(tmp_path):
    queue = Queue(tmp_path)
    queue.put("task", {})
    (token,) = queue.reserve("worker", now=0, lease_seconds=5)
    queue.compact()
    queue = Queue(tmp_path)
    before = queue.export()
    with pytest.raises(StaleLease):
        queue.ack(token, now=5)
    assert queue.export() == before
    assert Queue(tmp_path).export() == before


def test_checksum_failure_is_not_treated_as_a_torn_tail(tmp_path):
    queue = Queue(tmp_path)
    queue.put("one", {})
    path = queue.journal.active
    data = bytearray(path.read_bytes())
    data[-1] ^= 1
    path.write_bytes(data)
    with pytest.raises(CorruptStore):
        Queue(tmp_path)


def test_partial_sealed_segment_is_corruption(tmp_path):
    queue = Queue(tmp_path)
    queue.put("one", {})
    sealed = queue.journal.active
    queue.journal.rotate()
    sealed.write_bytes(sealed.read_bytes()[:-1])
    with pytest.raises(CorruptStore):
        Queue(tmp_path)


def test_sequence_gap_is_not_silently_accepted(tmp_path):
    queue = Queue(tmp_path)
    queue.put("one", {})
    with queue.journal.active.open("ab") as stream:
        stream.write(
            encode(
                {
                    "sequence": 3,
                    "commands": [
                        {
                            "op": "put",
                            "task_id": "gap",
                            "key": "gap",
                            "payload": {},
                            "available_at": 0,
                            "max_attempts": 3,
                        }
                    ],
                }
            )
        )
    with pytest.raises(CorruptStore):
        Queue(tmp_path)


@pytest.mark.parametrize("damage", ["missing", "checksum", "state", "pointer"])
def test_published_snapshot_damage_is_fatal(damage, tmp_path):
    queue = Queue(tmp_path)
    queue.put("one", {})
    queue.compact()
    pointer = read_document(tmp_path / "CURRENT")
    snapshot = tmp_path / pointer["snapshot"]
    if damage == "missing":
        snapshot.unlink()
    elif damage == "checksum":
        snapshot.write_bytes(snapshot.read_bytes().replace(b'"ready"', b'"wrong"'))
    elif damage == "state":
        document = read_document(snapshot)
        document["state"]["tasks"][0]["generation"] = 999
        write_document(snapshot, document)
    else:
        write_document(tmp_path / "CURRENT", {"snapshot": "../escape", "through": 1})
    with pytest.raises(CorruptStore):
        Queue(tmp_path)


def test_payload_mutation_cannot_change_original_request(tmp_path):
    payload = {"nested": [1]}
    queue = Queue(tmp_path)
    queue.put("one", payload)
    payload["nested"].append(2)
    (lease,) = queue.reserve("worker", now=0, lease_seconds=5)
    lease.payload["nested"].append(3)
    queue.inspect("one").payload["nested"].append(4)
    queue.compact()
    assert Queue(tmp_path).inspect("one").payload == {"nested": [1]}


def test_recovery_in_fresh_process_after_complete_ack_frame(tmp_path):
    queue = Queue(tmp_path)
    queue.put("one", {})
    (token,) = queue.reserve("worker", now=0, lease_seconds=10)
    queue.compact()
    queue = Queue(tmp_path, hook=CrashAt("append.synced"))
    with pytest.raises(InjectedCrash):
        queue.ack(token, now=1)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json,sys; from walqueue import Queue; "
            "print(json.dumps(Queue(sys.argv[1]).export(), sort_keys=True))",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=True,
        env=os.environ.copy(),
        timeout=20,
    )
    document = json.loads(completed.stdout)
    assert document["state"]["tasks"][0]["status"] == "done"


class MemoryQueue:
    """Independent dictionary model, intentionally unaware of the disk format."""

    def __init__(self):
        self.tasks = {}
        self.keys = {}

    def put(self, task_id, payload, available_at=0, max_attempts=3):
        self.keys[task_id] = {
            "task_id": task_id,
            "payload": deepcopy(payload),
            "available_at": available_at,
            "max_attempts": max_attempts,
        }
        self.tasks[task_id] = {
            "task_id": task_id,
            "payload": deepcopy(payload),
            "available_at": available_at,
            "max_attempts": max_attempts,
            "attempts": 0,
            "generation": 0,
            "status": "ready",
            "worker": None,
            "deadline": None,
        }

    def reserve(self, worker, now, duration, limit):
        for task in self.tasks.values():
            if task["status"] == "leased" and task["deadline"] <= now:
                task["available_at"] = task["deadline"]
                task["status"] = "dead" if task["attempts"] == task["max_attempts"] else "ready"
                task["deadline"] = task["worker"] = None
        eligible = sorted(
            [
                task
                for task in self.tasks.values()
                if task["status"] == "ready" and task["available_at"] <= now
            ],
            key=lambda task: (task["available_at"], task["task_id"]),
        )[:limit]
        for task in eligible:
            task["status"] = "leased"
            task["attempts"] += 1
            task["generation"] += 1
            task["worker"], task["deadline"] = worker, now + duration
        return [task["task_id"] for task in eligible]

    def finish(self, token, now, delay=None):
        task = self.tasks.get(token.task_id)
        if (
            task is None
            or task["status"] != "leased"
            or task["worker"] != token.worker
            or (task["generation"] != token.generation or task["deadline"] <= now)
        ):
            return False
        task["status"] = (
            "done"
            if delay is None
            else ("dead" if task["attempts"] == task["max_attempts"] else "ready")
        )
        if delay is not None:
            task["available_at"] = now + delay
        task["worker"] = task["deadline"] = None
        return True

    def document(self):
        return {"tasks": [self.tasks[key] for key in sorted(self.tasks)], "keys": self.keys}


@pytest.mark.parametrize("seed", range(16))
def test_generated_multistage_traces_match_memory_model(seed, tmp_path):
    randomizer = random.Random(seed)
    queue, oracle = Queue(tmp_path), MemoryQueue()
    tokens = []
    now = 0
    for step in range(70):
        choice = randomizer.randrange(10)
        if choice < 3:
            task_id = f"task-{step}"
            payload = {"step": step, "nested": [seed, -step]}
            available, attempts = now + randomizer.randrange(5), randomizer.randint(1, 4)
            queue.put(task_id, payload, available_at=available, max_attempts=attempts)
            oracle.put(task_id, payload, available, attempts)
        elif choice < 6:
            worker, duration, limit = (
                f"worker-{step % 2}",
                randomizer.randint(1, 8),
                randomizer.randint(1, 3),
            )
            leases = queue.reserve(worker, now=now, lease_seconds=duration, limit=limit)
            assert [token.task_id for token in leases] == oracle.reserve(
                worker, now, duration, limit
            )
            tokens.extend(leases)
        elif choice < 9 and tokens:
            token = randomizer.choice(tokens)
            delay = randomizer.randint(0, 4) if choice == 8 else None
            accepted = oracle.finish(token, now, delay)
            if accepted:
                if delay is None:
                    queue.ack(token, now=now)
                else:
                    queue.release(token, now=now, delay=delay)
            else:
                with pytest.raises(StaleLease):
                    queue.ack(token, now=now)
        else:
            queue.compact()
        assert queue.export()["state"] == oracle.document(), (seed, step)
        if step % 5 == 0:
            before = queue.export()
            queue = Queue(tmp_path)
            assert queue.export() == before, (seed, step, "restart")
        now += randomizer.randrange(3)
    queue.compact()
    assert Queue(tmp_path).export()["state"] == oracle.document()
