"""The KV state machine and the durability seam."""

import pytest

from tidewater.errors import ConfigurationError, StorageError
from tidewater.log import ENTRY_NOOP, Entry, RaftLog
from tidewater.statemachine import Command, KVStateMachine
from tidewater.storage import Storage


def test_state_machine_applies_in_order_and_digest_is_canonical():
    a, b = KVStateMachine(), KVStateMachine()
    cmds = [Command("set", "x", "1"), Command("incr", "x", "4"), Command("del", "y"),
            Command("cas", "x", value="9", expect="5"), Command("cas", "x", value="0", expect="nope")]
    for i, c in enumerate(cmds, start=1):
        a.apply(i, c)
        b.apply(i, c)
    assert a.get("x") == "9"
    assert a.last_result.ok is False and a.last_result.value == "9"
    assert a.digest() == b.digest()
    with pytest.raises(ValueError):
        a.apply(9, Command("set", "z", "1"))
    restored = KVStateMachine.from_snapshot_bytes(a.snapshot_bytes())
    assert restored.digest() == a.digest()


def test_command_validation():
    with pytest.raises(ValueError):
        Command("frob", "x")
    with pytest.raises(ValueError):
        Command("set", "")


def test_storage_always_policy_is_durable_immediately():
    storage = Storage("n1", ("n1", "n2", "n3"))
    storage.set_term(3, "n2")
    log = RaftLog([Entry(1, 3, ENTRY_NOOP)])
    storage.save_log(log)
    storage.crash()
    assert storage.current_term == 3 and storage.voted_for == "n2"
    assert storage.load_log().last_index == 1
    assert storage.lost_writes == 0


def test_storage_explicit_policy_loses_unsynced_writes():
    storage = Storage("n1", ("n1",), sync_policy="explicit")
    storage.set_term(1, "n1")
    storage.sync()
    storage.set_term(2, "n1")
    assert storage.dirty
    storage.crash()
    assert storage.current_term == 1
    assert storage.lost_writes == 1
    assert not storage.dirty


def test_storage_never_policy_makes_sync_a_noop():
    storage = Storage("n1", ("n1",), sync_policy="never")
    storage.set_term(4, None)
    assert storage.sync() is False
    storage.crash()
    assert storage.current_term == 0
    with pytest.raises(ConfigurationError):
        Storage("n1", ("n1",), sync_policy="sometimes")


def test_storage_enforces_term_and_vote_monotonicity():
    storage = Storage("n1", ("n1", "n2"))
    storage.set_term(2, "n2")
    with pytest.raises(StorageError):
        storage.set_term(1, None)
    with pytest.raises(StorageError):
        storage.set_term(2, "n1")
    storage.set_term(2, "n2")  # idempotent re-record is fine
    storage.set_term(3, None)
    assert storage.voted_for is None
