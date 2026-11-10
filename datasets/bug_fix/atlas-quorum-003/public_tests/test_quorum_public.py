"""Symptom-level checks for atlas-quorum-003: what the operators saw, not where."""

import pytest

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


def key_owned_by(db, owner):
    for index in range(512):
        key = f"k-{index}"
        if db.owner(key) == owner:
            return key
    raise AssertionError(f"no probe key is owned by {owner}")


def test_retiring_a_primary_moves_its_keys_rather_than_dropping_them(db):
    key = key_owned_by(db, "atlas-2")
    db.put(key, "kept")
    db.nodes["atlas-2"].drain()
    report = db.rebalance(["atlas-0", "atlas-1", "atlas-7"])
    assert report.moved_keys == [key]
    assert report.copied >= 1, report.notes
    assert db.nodes[db.owner(key)].store(db.shard_of(key)).resolve(key) is not None


def test_a_rebalance_without_a_retiring_replica_is_unchanged(db):
    key = key_owned_by(db, "atlas-2")
    db.put(key, "kept")
    report = db.rebalance(["atlas-0", "atlas-1", "atlas-7"])
    assert report.moved_keys == [key]
    assert db.get(key).value == "kept"
