"""Symptom-level checks for atlas-quorum-002: what the operators saw, not where."""

import pytest

from atlas.config import build as build_config
from atlas.errors import QuorumError
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


def test_a_cluster_with_two_replicas_retiring_is_not_readable(db):
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    db.nodes[order[1]].drain()
    db.nodes[order[2]].drain()
    with pytest.raises(QuorumError):
        db.get("k")


def test_a_cluster_with_one_replica_retiring_is_still_readable(db):
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    db.nodes[order[2]].drain()
    assert db.get("k").value == "one"
