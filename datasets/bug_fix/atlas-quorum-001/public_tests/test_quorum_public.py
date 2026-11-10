"""Symptom-level checks for atlas-quorum-001.

These are the complaints as the operators phrased them. They say what the
cluster did; they do not say where.
"""

import pytest

from atlas.antientropy import AntiEntropy
from atlas.config import build as build_config
from atlas.errors import QuorumError, StaleGenerationError
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


def generations(db, key):
    return sorted(record.generation for record in db.read_replicas(key))


def test_a_retiring_replica_does_not_make_up_the_quorum(db):
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    db.nodes[order[1]].drain()
    db.nodes.pop(order[2])
    with pytest.raises(QuorumError):
        db.put("k", "two", expected_generation=1)


def test_a_convergence_pass_finishes_while_a_replica_is_retiring(db):
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    db.nodes[order[2]].drain()
    gone = db.nodes.pop(order[2])
    db.put("k", "two", expected_generation=1)
    db.nodes[order[2]] = gone
    walk = AntiEntropy(db.nodes, placement=db.placement, width=4)
    walk.converge(db.shard_of("k"), epoch=db.placement.epoch(), repairer=db.repairer)
    assert generations(db, "k") == [2, 2, 2]


def test_one_read_is_enough_to_bring_a_returning_replica_level(db):
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    gone = db.nodes.pop(order[2])
    db.put("k", "two")
    db.nodes[order[2]] = gone
    assert db.get("k").value == "two"
    assert generations(db, "k") == [2, 2, 2]
    assert db.put("k", "three").record.generation == 3


def test_a_worker_that_fell_behind_cannot_retake_the_key(db):
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    gone = db.nodes.pop(order[0])
    db.put("k", "two")
    db.nodes[order[0]] = gone
    with pytest.raises(StaleGenerationError):
        db.put("k", "three")
