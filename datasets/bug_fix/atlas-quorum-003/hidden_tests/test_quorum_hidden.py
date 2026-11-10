"""Witness scenarios for atlas-quorum-003: a retiring replica is still a holder.

The base repository passes every test here and the mutated repository fails
the witnesses. The guards pass in both states and pin the parts of the rule
that already hold, so a fix that trades one half of it for the other is
caught.
"""

import pytest

from atlas.antientropy import AntiEntropy
from atlas.config import build as build_config
from atlas.errors import QuorumShortfallError
from atlas.placement import Plan
from atlas.store import AtlasBuilder


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
def db(tmp_path):
    return AtlasBuilder().config(make_config()).root(tmp_path / "c").build()


def key_owned_by(db, owner, prefix="k"):
    for index in range(512):
        key = f"{prefix}-{index}"
        if db.owner(key) == owner:
            return key
    raise AssertionError(f"no probe key is owned by {owner}")


def key_moving_to(db, primary, newcomer, prefix="m"):
    """A key owned by ``primary`` now whose owner becomes ``newcomer`` once ``primary`` retires."""

    survivors = [name for name in db.nodes if name != primary] + [newcomer]
    target = Plan.build(db.placement.epoch() + 1, survivors, vnodes=int(db.config["vnodes"]))
    for index in range(2048):
        key = f"{prefix}-{index}"
        if db.owner(key) == primary and target.owner(key) == newcomer:
            return key
    raise AssertionError(f"no probe key moves from {primary} to {newcomer}")


def copies(db, key):
    shard = db.shard_of(key)
    return {
        name: record.value
        for name in db.replicas_for(key)
        if (record := db.nodes[name].store(shard).resolve(key)) is not None
    }


def retire(db, primary, key):
    order = list(db.replicas_for(key))
    db.nodes[primary].drain()
    return db.rebalance([name for name in order if name != primary] + ["atlas-7"])


def test_witness_a_key_whose_primary_is_retiring_is_streamed_to_its_new_primary(db):
    primary = "atlas-2"
    key = key_owned_by(db, primary)
    db.put(key, "kept")
    report = retire(db, primary, key)
    assert report.moved_keys == [key]
    assert report.copied >= 1, report.notes
    assert report.released, report.notes
    assert db.owner(key) != primary
    assert copies(db, key).get(db.owner(key)) == "kept"


def test_witness_the_rebalance_does_not_leave_the_moved_key_under_replicated(db):
    primary = "atlas-0"
    key = key_moving_to(db, primary, "atlas-7")
    db.put(key, "one")
    db.put(key, "two")
    retire(db, primary, key)
    held = copies(db, key)
    assert db.owner(key) == "atlas-7"
    assert db.owner(key) in held, held
    assert len(held) >= 2 and set(held.values()) == {"two"}, held
    # Losing the new primary must not lose the key: the other copies answer.
    gone = db.nodes.pop(db.owner(key))
    try:
        assert db.get(key).value == "two"
    finally:
        db.nodes[gone.node_id] = gone


def test_witness_a_converged_drain_followed_by_a_rebalance_carries_the_latest_version(db):
    primary = "atlas-1"
    key = key_owned_by(db, primary)
    db.put(key, "first")
    order = list(db.replicas_for(key))
    gone = db.nodes.pop(order[2])
    db.put(key, "second", expected_generation=1)
    db.nodes[order[2]] = gone
    db.nodes[primary].drain()
    walk = AntiEntropy(db.nodes, placement=db.placement, width=4)
    walk.converge(db.shard_of(key), epoch=db.placement.epoch(), repairer=db.repairer)
    report = db.rebalance([name for name in order if name != primary] + ["atlas-7"])
    assert report.moved_keys == [key]
    assert report.copied >= 1, report.notes
    assert copies(db, key).get(db.owner(key)) == "second"
    assert db.get(key).value == "second"


def test_a_retiring_replica_is_not_a_vote(db):
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    db.nodes[order[1]].drain()
    db.nodes.pop(order[2])
    with pytest.raises(QuorumShortfallError, match="acks below quorum for epoch 1"):
        db.put("k", "two", expected_generation=1)


def test_a_retiring_replica_is_still_written_and_still_repaired(db):
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    leaving = order[2]
    db.nodes[leaving].drain()
    db.put("k", "two")
    assert copies(db, "k")[leaving] == "two"
    gone = db.nodes.pop(leaving)
    db.put("k", "three")
    db.nodes[leaving] = gone
    walk = AntiEntropy(db.nodes, placement=db.placement, width=4)
    walk.converge(db.shard_of("k"), epoch=db.placement.epoch(), repairer=db.repairer)
    assert copies(db, "k")[leaving] == "three"
