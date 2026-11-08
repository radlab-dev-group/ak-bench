"""Visible checks for the five invariants. These are not the whole evidence.

They fail on a cluster that has lost one of the rules and pass on a correct
one, and they are deliberately less surgical than the hidden scenarios: they
say which rule broke, not which line broke it.
"""

import pytest

from atlas.config import build as build_config
from atlas.errors import StaleGenerationError
from atlas.faults import CrashPlan, SimulatedCrash
from atlas.repair import ReadRepairer
from atlas.storage import ShardStorage
from atlas.store import AtlasBuilder
from atlas.values import Record
from atlas.vclock import VersionVector


def make_config():
    return build_config(
        path="none.toml",
        env={},
        values={
            "shards": 2,
            "replication_factor": 3,
            "read_consistency": 2,
            "write_consistency": 2,
            "vnodes": 8,
        },
    )


def test_the_new_primary_of_a_rebalanced_key_holds_it(tmp_path):
    db = AtlasBuilder().config(make_config()).root(tmp_path / "c").build()
    db.put("moved", "value")
    db.rebalance(["atlas-0", "atlas-1", "atlas-3"])
    shard = db.shard_of("moved")
    primary = db.owner("moved")
    assert db.nodes[primary].store(shard).resolve("moved") is not None


def test_the_generation_check_is_an_equality(tmp_path):
    db = AtlasBuilder().config(make_config()).root(tmp_path / "c").build()
    db.put("k", 1)
    with pytest.raises(StaleGenerationError):
        db.put("k", 2, expected_generation=99)


def test_the_torn_tail_keeps_a_committed_transaction(tmp_path):
    store = ShardStorage(tmp_path / "s", 0)
    store.put("keep", 1, writer="n")
    store.crash = CrashPlan(at="mid_frame", times=1, tear_bytes=200)
    with pytest.raises(SimulatedCrash):
        store.put("gone", 2, writer="n")
    reopened = ShardStorage(tmp_path / "s", 0)
    assert reopened.recovery.torn is True
    assert reopened.get("keep") is not None


def test_concurrent_writes_resolve_to_the_greatest_writer_identifier():
    left = Record.put("k", "left", generation=1, vector=VersionVector.single("aaa", 1), writer="aaa")
    right = Record.put("k", "right", generation=1, vector=VersionVector.single("zzz", 1), writer="zzz")
    winner, _losers, by_tie = ReadRepairer.choose(ReadRepairer.__new__(ReadRepairer), [left, right])
    assert by_tie is True
    assert winner is right


def test_a_snapshot_record_is_not_reapplied(tmp_path):
    store = ShardStorage(tmp_path / "s", 0)
    store.put("counter", {"n": 1}, writer="n")
    store.snapshot()
    store.put("counter", {"n": 2}, writer="n")
    reopened = store.reopen()
    assert reopened.get("counter").value == {"n": 2}


def test_the_snapshot_records_are_skipped_on_replay(tmp_path):
    store = ShardStorage(tmp_path / "s", 0)
    for index in range(3):
        store.put(f"k{index}", index, writer="n")
    store.snapshot()
    store.put("after", 1, writer="n")
    reopened = store.reopen()
    assert reopened.recovery.skipped >= 3
