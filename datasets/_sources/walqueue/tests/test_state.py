"""Pure transition tests deliberately independent of durable recovery."""

from copy import deepcopy

import pytest
from walqueue import CorruptStore, KeyConflict, StaleLease
from walqueue.state import State


def put(task_id="one", **overrides):
    return {
        "op": "put",
        "task_id": task_id,
        "key": task_id,
        "payload": {"value": 3},
        "available_at": 0,
        "max_attempts": 3,
        **overrides,
    }


def lease(**overrides):
    return {
        "op": "lease",
        "task_id": "one",
        "worker": "worker",
        "now": 0,
        "deadline": 5,
        **overrides,
    }


def finish(operation, **overrides):
    return {
        "op": operation,
        "task_id": "one",
        "worker": "worker",
        "generation": 1,
        "now": 1,
        **overrides,
    }


def test_state_clone_does_not_share_payloads_or_idempotency():
    state = State()
    state.apply([put()])
    clone = state.clone()
    clone.tasks["one"].payload["value"] = 99
    clone.keys["one"]["payload"]["value"] = 88
    assert state.tasks["one"].payload == {"value": 3}
    assert state.keys["one"]["payload"] == {"value": 3}


def test_put_identity_keeps_original_schedule_after_release():
    state = State()
    command = put(available_at=2)
    state.apply([command, lease(now=2, deadline=8)])
    state.apply([finish("release", now=3, available_at=7)])
    state.apply([deepcopy(command)])
    assert state.tasks["one"].available_at == 7
    assert state.tasks["one"].generation == 1
    with pytest.raises(KeyConflict):
        state.apply([put(available_at=7)])


@pytest.mark.parametrize(
    "overrides", [{"worker": "other"}, {"generation": 2}, {"now": 5}, {"task_id": "missing"}]
)
def test_rejected_ack_is_a_pure_validation_failure(overrides):
    state = State()
    state.apply([put(), lease()])
    before = state.document()
    with pytest.raises(StaleLease):
        state.apply([finish("ack", **overrides)])
    assert state.document() == before


def test_expiration_preserves_the_old_deadline_as_next_schedule():
    state = State()
    state.apply([put(), lease()])
    state.apply([{"op": "expire", "task_id": "one", "now": 10}])
    task = state.tasks["one"]
    assert (task.status, task.available_at, task.attempts, task.generation) == ("ready", 5, 1, 1)
    assert task.worker is task.deadline is None
    state.apply([lease(now=10, deadline=12)])
    assert state.tasks["one"].generation == 2


@pytest.mark.parametrize("operation", ["release", "expire"])
def test_exhausted_attempts_become_terminal(operation):
    state = State()
    state.apply([put(max_attempts=1), lease()])
    command = (
        finish("release", available_at=3)
        if operation == "release"
        else {"op": "expire", "task_id": "one", "now": 5}
    )
    state.apply([command])
    assert state.tasks["one"].status == "dead"
    assert state.keys["one"]["max_attempts"] == 1
    assert state.clone().document() == state.document()


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempts", -1),
        ("generation", 99),
        ("status", "unknown"),
        ("worker", "ghost"),
        ("deadline", 3),
        ("max_attempts", 0),
    ],
)
def test_invalid_snapshot_records_are_rejected(field, value):
    state = State()
    state.apply([put()])
    document = state.document()
    document["tasks"][0][field] = value
    with pytest.raises(CorruptStore):
        State.restore(document)


def test_snapshot_requires_exactly_one_original_identity_per_task():
    state = State()
    state.apply([put()])
    document = state.document()
    document["keys"] = {}
    with pytest.raises(CorruptStore):
        State.restore(document)
    document = state.document()
    document["keys"]["duplicate"] = deepcopy(document["keys"]["one"])
    with pytest.raises(CorruptStore):
        State.restore(document)


def test_put_copies_nested_payload_before_external_mutation():
    state = State()
    command = put(payload={"nested": [1, {"two": 2}]})
    state.apply([command])
    command["payload"]["nested"][1]["two"] = 9
    assert state.tasks["one"].payload == {"nested": [1, {"two": 2}]}
