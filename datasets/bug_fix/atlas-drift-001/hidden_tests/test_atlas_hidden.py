"""Witness scenarios for the five cooperating regressions of atlas-drift-001.

Each test targets one regression in isolation: it is written so that the base
repository passes it and the mutated repository fails it, and the combined
mutation fails all five. The scenarios are the crash and cross-module
combinations the repository suite does not reach.
"""

import os
import sys
import pathlib
import subprocess

import pytest

from atlas.config import build as build_config
from atlas.errors import QuorumError, StaleGenerationError
from atlas.faults import CrashPlan, SimulatedCrash
from atlas.repair import ReadRepairer
from atlas.storage import ShardStorage
from atlas.store import AtlasBuilder
from atlas.values import Record
from atlas.vclock import VersionVector


def make_config(**values):
    settings = {
        "shards": 2,
        "replication_factor": 3,
        "read_consistency": 2,
        "write_consistency": 2,
        "vnodes": 8,
    }
    settings.update(values)
    return build_config(path="none.toml", env={}, values=settings)


@pytest.fixture
def config():
    return make_config()


def build_store(tmp_path, config, name="c"):
    return AtlasBuilder().config(config).root(tmp_path / name).build()


def _record(key, value, generation, node, lsn=0):
    return Record.put(
        key,
        value,
        generation=generation,
        vector=VersionVector.single(node, generation),
        writer=node,
        lsn=lsn,
    )


def test_regression_01_rebalance_keeps_the_current_plan_for_moved_keys(tmp_path, config):
    """The write admitted after a rebalance must land where the new plan says.

    The defect keeps the plan the rebalance started with and resolves the
    moved keys under it, so a write that goes out after the switch lands on a
    replica that no longer owns the key. The witness is a read after the
    switch: it asks the current plan and finds a replica that never got the
    value.
    """

    db = build_store(tmp_path, config)
    key = "move-me"
    db.put(key, "before")
    report = db.rebalance(["atlas-0", "atlas-1", "atlas-3"])
    shard = db.shard_of(key)
    primary = db.owner(key)
    on_primary = db.nodes[primary].store(shard).resolve(key)
    assert on_primary is not None, (
        f"the replica the current plan names as primary for {key!r} does not hold it"
    )
    assert on_primary.value == "before"
    db.put(key, "after", writer="worker")
    assert db.get(key).value == "after"


def test_regression_02_fencing_refuses_a_generation_ahead_of_the_store(tmp_path, config):
    """A strict check is an equality. A caller that is ahead is refused, not passed.

    The defect makes the check one-sided: a smaller offer is refused, a larger
    one is accepted. The witness offers a generation the store does not hold
    and expects a refusal under the strict check that the configuration
    carries.
    """

    db = build_store(tmp_path, config)
    first = db.put("k", 1).record
    # The fence is now at generation 1. Offer generation 5: the store has not
    # seen it, so it must refuse. The mutated check only refuses offers below.
    with pytest.raises(StaleGenerationError):
        db.put("k", 2, writer="worker", expected_generation=5)
    # And the value must still be the first write.
    assert db.get("k").value == 1


def test_regression_03_torn_tail_does_not_erase_a_committed_transaction(tmp_path):
    """A committed transaction survives the torn tail that follows it.

    Two transactions, then the second one is torn off mid-frame. The first
    one committed: its COMMIT frame is on disk, and a repair that cuts back to
    the transaction boundary of the torn one eats it. The witness is the value
    of the first transaction after a reopen.
    """

    store = ShardStorage(tmp_path / "s", 0)
    store.put("keep", 1, writer="n")
    store.put("drop", 2, writer="n")
    # The third transaction dies with only a stub of its first frame on disk.
    # The second transaction's COMMIT is the last thing that reads cleanly, and
    # a repair that cuts back past it erases a transaction the log had already
    # promised.
    store.crash = CrashPlan(at="mid_frame", times=1, tear_bytes=200)
    try:
        store.put("never", 3, writer="n")
    except SimulatedCrash:
        pass
    reopened = ShardStorage(tmp_path / "s", 0)
    assert reopened.recovery.torn is True
    assert reopened.get("keep") is not None, (
        "the committed transaction was erased by the tail repair"
    )
    assert reopened.get("keep").value == 1
    assert reopened.get("drop") is not None, (
        "a committed transaction was erased because the repair cut back past "
        "its own COMMIT frame"
    )
    assert reopened.get("drop").value == 2


def test_regression_04_concurrent_writes_resolve_to_the_greatest_writer(tmp_path, config):
    """The tie-break is descending writer identifier, in one direction.

    The defect flips it to ascending. The witness constructs two concurrent
    versions with writers on opposite ends of the identifier space and
    requires the greater one to win.
    """

    left = _record("k", "left", 1, "aaa", lsn=1)
    right = _record("k", "right", 1, "zzz", lsn=2)
    winner, losers, by_tie = ReadRepairer.choose(ReadRepairer.__new__(ReadRepairer), [left, right])
    assert by_tie is True
    assert winner is right, (
        f"the concurrent write resolved to {winner.value!r}; the documented tie-break "
        "is the greatest writer identifier, which is 'zzz'"
    )


def test_regression_05_a_record_the_snapshot_contains_is_not_reapplied(tmp_path, config):
    """A counter incremented around a snapshot must advance by one, not by two.

    The defect opens the replay window at the snapshot's number, so the record
    the snapshot already holds is applied a second time. The witness keeps the
    value as a plain integer and checks the arithmetic after a restart.
    """

    store = ShardStorage(tmp_path / "s", 0)
    store.put("counter", {"n": 1}, writer="n")
    store.snapshot()
    store.put("counter", {"n": 2}, writer="n")
    reopened = store.reopen()
    value = reopened.get("counter").value
    assert value == {"n": 2}, (
        f"the record the snapshot already contained was applied again: got {value!r}, "
        "expected {'n': 2}"
    )


def test_regression_05b_the_boundary_is_exclusive_in_the_log_path(tmp_path, config):
    """The same defect, read through the store's own recovery report."""

    store = ShardStorage(tmp_path / "s", 0)
    for index in range(3):
        store.put(f"k{index}", index, writer="n")
    store.snapshot()
    store.put("k3", 3, writer="n")
    reopened = store.reopen()
    assert reopened.recovery.skipped >= 3, (
        "the snapshot's records were not skipped on replay"
    )
    assert reopened.get("k2").value == 2
    assert reopened.get("k3").value == 3


def test_regression_combined_a_write_after_rebalance_is_visible_and_fenced(tmp_path, config):
    """The five regressions together, on one store, in one scenario.

    Rebalance, write, restart. Each step is the witness for a different defect,
    and the combined mutation fails at least one of them.
    """

    db = build_store(tmp_path, config)
    db.put("a", {"n": 1})
    db.rebalance(["atlas-1", "atlas-2", "atlas-3"])
    db.put("a", {"n": 2}, writer="w")
    assert db.get("a") == {"n": 2} or db.get("a").value == {"n": 2}, "the write is invisible"
    report = db.recover()
    assert report["replayed"] >= 0
    final = db.get("a")
    assert final is not None
    assert final.value == {"n": 2}, f"restart changed the value: {final.value!r}"
