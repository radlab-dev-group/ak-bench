"""Symptom-level checks for atlas-quorum-004: what the operators saw, not where."""

import pytest

from atlas.antientropy import AntiEntropy
from atlas.config import build as build_config
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


def test_a_convergence_pass_with_nothing_retiring_finishes_clean(db):
    shard = db.shard_of("k")
    order = list(db.replicas_for("k"))
    db.nodes[order[0]].store(shard).put("k", "a", writer="alpha")
    db.nodes[order[0]].store(shard).put("k", "b", writer="zeta")
    db.nodes[order[1]].store(shard).put("k", "a", writer="zeta")
    db.nodes[order[1]].store(shard).put("k", "b", writer="alpha")
    db.nodes[order[2]].store(shard).put("k", "a", writer="alpha")
    walk = AntiEntropy(db.nodes, placement=db.placement, width=4)
    walk.converge(shard, epoch=db.placement.epoch(), repairer=db.repairer)
    assert sorted(record.generation for record in db.read_replicas("k")) == [2, 2, 2]


def test_a_healthy_cluster_converges_without_repairing_anything(db):
    db.put("k", "one")
    db.put("j", "two")
    walk = AntiEntropy(db.nodes, placement=db.placement, width=4)
    for shard in range(2):
        assert walk.converge(shard, epoch=db.placement.epoch(), repairer=db.repairer).repaired == []
