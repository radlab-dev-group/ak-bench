"""Witness scenarios for atlas-quorum-002: the read side of the quorum rule.

The base repository passes every test here and the mutated repository fails
the witnesses. The guards pass in both states; they exist so that a fix which
moves the rule instead of restoring it is caught.
"""

import pytest

from atlas.antientropy import AntiEntropy
from atlas.config import build as build_config
from atlas.errors import QuorumError, QuorumShortfallError
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


def versions(db, key):
    shard = db.shard_of(key)
    return [
        None if (record := db.nodes[name].store(shard).resolve(key)) is None else (record.generation, record.value)
        for name in db.replicas_for(key)
    ]


def test_witness_a_read_answered_by_retiring_replicas_has_no_quorum(db):
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    db.nodes[order[1]].drain()
    db.nodes[order[2]].drain()
    with pytest.raises(QuorumShortfallError, match="acks below quorum for epoch 1") as caught:
        db.get("k")
    assert isinstance(caught.value, QuorumError)
    assert (caught.value.phase, caught.value.counted, caught.value.needed) == ("read", 1, 2)


def test_witness_a_read_with_one_replica_gone_and_one_retiring_is_refused(db):
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    db.nodes[order[1]].drain()
    db.nodes.pop(order[2])
    with pytest.raises(QuorumShortfallError, match="acks below quorum for epoch 1"):
        db.resolve("k")


def test_witness_a_write_without_a_read_quorum_cannot_learn_its_generation(db):
    """The write path reads the current generation first; with two replicas retiring it must stop there."""

    db.put("k", "one")
    order = list(db.replicas_for("k"))
    db.nodes[order[1]].drain()
    db.nodes[order[2]].drain()
    with pytest.raises(QuorumShortfallError, match="read of 'k'"):
        db.put("k", "two")
    assert all(item == (1, "one") for item in versions(db, "k"))


def test_a_retiring_replica_still_answers_and_its_answer_is_repaired(db):
    """One replica is retiring and behind: the read still resolves and brings it level."""

    db.put("k", "one")
    order = list(db.replicas_for("k"))
    leaving = order[2]
    gone = db.nodes.pop(leaving)
    db.put("k", "two")
    db.nodes[leaving] = gone
    db.nodes[leaving].drain()
    assert db.get("k").value == "two"
    assert versions(db, "k") == [(2, "two")] * 3


def test_a_retiring_acknowledgment_does_not_count_toward_the_write_quorum(db):
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    db.nodes[order[1]].drain()
    db.nodes.pop(order[2])
    with pytest.raises(QuorumShortfallError, match="write of 'k'"):
        db.put("k", "two", expected_generation=1)


def test_a_convergence_pass_still_repairs_the_retiring_replica(db):
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    leaving = order[2]
    db.nodes[leaving].drain()
    gone = db.nodes.pop(leaving)
    db.put("k", "two", expected_generation=1)
    db.nodes[leaving] = gone
    walk = AntiEntropy(db.nodes, placement=db.placement, width=4)
    report = walk.converge(db.shard_of("k"), epoch=db.placement.epoch(), repairer=db.repairer)
    assert report.repaired == ["k"]
    assert versions(db, "k") == [(2, "two")] * 3
