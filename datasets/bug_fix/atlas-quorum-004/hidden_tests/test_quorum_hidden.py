"""Witness scenarios for atlas-quorum-004: the same complaint, a different cause.

A convergence pass reports a shard that did not converge, with the same
exception and the same message shape as a pass that skipped a retiring
replica. Nothing here is retiring. The base repository passes every test; the
mutated repository fails the witnesses; the guards pin the participation rule
so that a fix which reaches for it instead of for the actual cause is caught.
"""

import pytest

from atlas.antientropy import AntiEntropy
from atlas.config import build as build_config
from atlas.errors import QuorumShortfallError
from atlas.store import AtlasBuilder
from atlas.values import Record
from atlas.vclock import VersionVector, compare


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


def converge(db, key):
    walk = AntiEntropy(db.nodes, placement=db.placement, width=4)
    return walk.converge(db.shard_of(key), epoch=db.placement.epoch(), repairer=db.repairer)


def versions(db, key):
    shard = db.shard_of(key)
    return [
        None if (record := db.nodes[name].store(shard).resolve(key)) is None else (record.generation, record.vector)
        for name in db.replicas_for(key)
    ]


def two_writers_in_both_orders(db, key, *, lagging_index):
    """Replicas see the same two writers in opposite orders; one replica saw only the first."""

    shard = db.shard_of(key)
    order = list(db.replicas_for(key))
    for index, name in enumerate(order):
        store = db.nodes[name].store(shard)
        if index == lagging_index:
            store.put(key, "alpha-only", writer="alpha")
            continue
        first, second = ("alpha", "zeta") if index % 2 == 0 else ("zeta", "alpha")
        store.put(key, f"{first}-first", writer=first)
        store.put(key, "both", writer=second)
    return order


def test_witness_a_vector_is_the_same_vector_whichever_order_its_writers_arrived_in():
    forward = VersionVector.new({"alpha": 1, "zeta": 1})
    backward = VersionVector.new([("zeta", 1), ("alpha", 1)])
    assert forward == backward
    assert hash(forward) == hash(backward)
    assert compare(forward, backward) == 0
    assert VersionVector.single("zeta").increment("alpha") == VersionVector.single("alpha").increment("zeta")


def test_witness_a_convergence_pass_is_clean_when_replicas_agree_through_different_histories(db):
    order = two_writers_in_both_orders(db, "k", lagging_index=2)
    report = converge(db, "k")
    assert report.repaired == ["k"]
    held = versions(db, "k")
    assert len(set(held)) == 1, held
    assert held[0][0] == 2


def test_a_read_sees_one_version_when_two_replicas_hold_it_through_different_histories(db):
    two_writers_in_both_orders(db, "k", lagging_index=1)
    assert db.get("k").value == "both"
    held = versions(db, "k")
    assert len(set(held)) == 1, held
    assert db.get("k").value == "both"
    assert versions(db, "k") == held


def test_witness_records_with_equal_vectors_are_the_same_version_to_the_memtable(db):
    shard = db.shard_of("k")
    name = db.replicas_for("k")[0]
    store = db.nodes[name].store(shard)
    store.put("k", "one", writer="alpha")
    store.put("k", "two", writer="zeta")
    mirror = Record.put(
        "k",
        "two",
        generation=2,
        vector=VersionVector.new([("zeta", 1), ("alpha", 1)]),
        writer="zeta",
        lsn=store.resolve("k").lsn,
    )
    store.apply_records([mirror], reconcile=True)
    assert store.resolve("k").vector == mirror.vector
    assert store.state.stats()["keys"] == 1


def test_a_retiring_acknowledgment_still_does_not_count(db):
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    db.nodes[order[1]].drain()
    db.nodes.pop(order[2])
    with pytest.raises(QuorumShortfallError, match="acks below quorum for epoch 1"):
        db.put("k", "two", expected_generation=1)


def test_a_retiring_replica_is_still_repaired_by_the_pass(db):
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    leaving = order[2]
    db.nodes[leaving].drain()
    gone = db.nodes.pop(leaving)
    db.put("k", "two", expected_generation=1)
    db.nodes[leaving] = gone
    report = converge(db, "k")
    assert report.repaired == ["k"]
    assert len(set(versions(db, "k"))) == 1
