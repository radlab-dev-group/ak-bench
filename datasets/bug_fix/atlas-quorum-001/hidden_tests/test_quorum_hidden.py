"""Witness scenarios for the four cooperating regressions of atlas-quorum-001.

Each witness targets one regression in isolation: the base repository passes
it and the mutated repository fails it. The remaining scenarios are the
multi-phase runs — partition, repair, drain, rebalance — in which the four
meet, and the guards that refuse the fixes that look right from one module
and are wrong from the next.
"""

import pytest

from atlas.antientropy import AntiEntropy
from atlas.config import build as build_config
from atlas.errors import ConvergenceError, QuorumError, QuorumShortfallError, StaleGenerationError
from atlas.faults import NO_CRASH, CrashPlan, SimulatedCrash
from atlas.fencing import FenceBook
from atlas.membership import Membership
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
def config():
    return make_config()


def build_store(tmp_path, config, name="c"):
    return AtlasBuilder().config(config).root(tmp_path / name).build()


def key_owned_by(db, owner, prefix="k"):
    for index in range(512):
        key = f"{prefix}-{index}"
        if db.owner(key) == owner:
            return key
    raise AssertionError(f"no probe key is owned by {owner}")


def versions(db, key):
    """(generation, vector, value) as each replica the plan names reports it."""

    shard = db.shard_of(key)
    found = []
    for name in db.replicas_for(key):
        record = db.nodes[name].store(shard).resolve(key)
        found.append(None if record is None else (record.generation, record.vector, record.value))
    return found


def converge(db, key):
    walk = AntiEntropy(db.nodes, placement=db.placement, width=4)
    return walk.converge(db.shard_of(key), epoch=db.placement.epoch(), repairer=db.repairer)


# ----------------------------------------------------------------- witnesses


def test_witness_01_a_draining_acknowledgment_does_not_count_toward_the_write_quorum(tmp_path, config):
    """Two copies are durable, one of them on a replica that is leaving; the write has one vote."""

    db = build_store(tmp_path, config)
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    db.nodes[order[1]].drain()
    gone = db.nodes.pop(order[2])
    try:
        with pytest.raises(QuorumShortfallError, match="acks below quorum for epoch 1"):
            db.put("k", "two", expected_generation=1)
    finally:
        db.nodes[order[2]] = gone


def test_witness_02_convergence_repairs_a_draining_replica_the_plan_still_names(tmp_path, config):
    """A replica that is leaving still holds the key; the pass brings it to the winner."""

    db = build_store(tmp_path, config)
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    leaving = order[2]
    db.nodes[leaving].drain()
    gone = db.nodes.pop(leaving)
    db.put("k", "two", expected_generation=1)
    db.nodes[leaving] = gone
    report = converge(db, "k")
    assert report.repaired == ["k"], report
    assert len(set(versions(db, "k"))) == 1, versions(db, "k")
    assert versions(db, "k")[0][2] == "two"


def test_witness_03_repair_carries_the_winner_unchanged_and_a_second_read_is_quiet(tmp_path, config):
    """After one read every replica holds the same version, and the store's generation matches the lease."""

    db = build_store(tmp_path, config)
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    gone = db.nodes.pop(order[2])
    db.put("k", "two")
    db.nodes[order[2]] = gone
    assert db.get("k").value == "two"
    first = versions(db, "k")
    assert len(set(first)) == 1, first
    assert first[0][0] == 2
    assert db.get("k").value == "two"
    assert versions(db, "k") == first
    assert db.current_generation("k") == db.generation_at("k") == 2


def test_witness_04_the_lease_never_moves_backwards_or_sideways():
    """A holder offering a generation at or below the one on record is refused and the lease stays."""

    fence = FenceBook(Membership(1))
    fence.advance_lease("k", "worker-a", 1)
    fence.advance_lease("k", "worker-a", 2)
    with pytest.raises(StaleGenerationError, match="offered generation 2 but the current generation is 2"):
        fence.advance_lease("k", "worker-b", 2)
    with pytest.raises(StaleGenerationError, match="offered generation 2 but the current generation is 1"):
        fence.advance_lease("k", "worker-b", 1)
    lease = fence.lease("k")
    assert (lease.holder, lease.generation) == ("worker-a", 2)


# ----------------------------------------------------- multi-phase scenarios


def test_a_replica_that_comes_back_behind_cannot_take_the_lease_sideways(tmp_path, config):
    """The first acknowledgment of a write comes from a replica that missed the previous one."""

    db = build_store(tmp_path, config)
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    gone = db.nodes.pop(order[0])
    db.put("k", "two")
    db.nodes[order[0]] = gone
    with pytest.raises(StaleGenerationError, match="offered generation 2 but the current generation is 2"):
        db.put("k", "three")
    assert db.generation_at("k") == 2


def test_partition_repair_rebalance_keeps_the_latest_value_through_a_drain(tmp_path, config):
    """A crash mid-write, a convergence pass over a draining replica, a rebalance away from it."""

    db = build_store(tmp_path, config)
    key = key_owned_by(db, "atlas-1")
    db.put(key, "v1")
    order = list(db.replicas_for(key))
    primary, last = order[0], order[2]
    assert primary == "atlas-1"
    shard = db.shard_of(key)
    db.nodes[last].store(shard).crash = CrashPlan(at="before_append")
    with pytest.raises(SimulatedCrash):
        db.put(key, "v2")
    db.nodes[last].store(shard).crash = NO_CRASH
    assert versions(db, key)[2][0] == 1
    db.nodes[primary].drain()
    report = converge(db, key)
    assert report.repaired == [key]
    assert len(set(versions(db, key))) == 1
    db.rebalance([name for name in order if name != primary] + ["atlas-7"])
    assert primary not in db.replicas_for(key)
    assert db.get(key).value == "v2"
    assert db.nodes[db.owner(key)].store(shard).resolve(key).value == "v2"
    assert all(item is None or item[2] == "v2" for item in versions(db, key)), versions(db, key)


def test_a_rebalance_away_from_a_draining_primary_streams_its_latest_copy(tmp_path, config):
    db = build_store(tmp_path, config)
    primary = "atlas-2"
    key = key_owned_by(db, primary)
    db.put(key, "first")
    order = list(db.replicas_for(key))
    gone = db.nodes.pop(order[1])
    db.put(key, "second", expected_generation=1)
    db.nodes[order[1]] = gone
    db.nodes[primary].drain()
    converge(db, key)
    db.rebalance([name for name in order if name != primary] + ["atlas-7"])
    assert db.get(key).value == "second"
    assert all(item is not None and item[0] == 2 for item in versions(db, key)), versions(db, key)


def test_a_draining_replica_that_holds_the_newest_copy_is_the_source_of_convergence(tmp_path, config):
    """The leaving replica is the only one with generation two; the pass must read from it."""

    db = build_store(tmp_path, config)
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    leaving = order[0]
    shard = db.shard_of("k")
    db.nodes[leaving].store(shard).put("k", "newest", writer="node-0")
    db.nodes[leaving].drain()
    report = converge(db, "k")
    assert report.repaired == ["k"]
    assert all(item is not None and item[2] == "newest" for item in versions(db, "k")), versions(db, "k")


# ------------------------------------------------------------------- guards


def test_a_cluster_with_only_draining_replicas_left_cannot_take_a_write(tmp_path, config):
    db = build_store(tmp_path, config)
    order = list(db.replicas_for("k"))
    db.nodes[order[1]].drain()
    db.nodes[order[2]].drain()
    with pytest.raises(QuorumShortfallError, match="acks below quorum for epoch 1") as caught:
        db.put("k", "one", expected_generation=0)
    assert isinstance(caught.value, QuorumError)
    assert caught.value.counted == 1


def test_a_write_still_lands_on_a_draining_replica(tmp_path, config):
    db = build_store(tmp_path, config)
    order = list(db.replicas_for("k"))
    db.nodes[order[2]].drain()
    db.put("k", "one")
    assert all(item is not None and item[0] == 1 for item in versions(db, "k")), versions(db, "k")


def test_a_write_that_bypassed_admission_is_refused_at_the_next_write(tmp_path, config):
    db = build_store(tmp_path, config)
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    db.nodes[order[2]].store(db.shard_of("k")).put("k", "rogue", writer="zeta")
    with pytest.raises(StaleGenerationError, match="offered generation 2 but the current generation is 1"):
        db.put("k", "two")


def test_acknowledging_a_generation_ahead_of_the_lease_is_refused(tmp_path, config):
    db = build_store(tmp_path, config)
    db.put("k", "one")
    with pytest.raises(StaleGenerationError, match="offered generation 2 but the current generation is 1"):
        db.acknowledge("k", 2)


def test_concurrent_writers_converge_to_the_greatest_writer_on_every_replica(tmp_path, config):
    db = build_store(tmp_path, config)
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    shard = db.shard_of("k")
    db.nodes[order[1]].store(shard).put("k", "from-zeta", writer="zeta")
    db.nodes[order[2]].store(shard).put("k", "from-alpha", writer="alpha")
    assert db.get("k").value == "from-zeta"
    held = versions(db, "k")
    assert len(set(held)) == 1, held
    assert held[0][0] == 2
    assert held[0][1].as_map == {"node-0": 1, "zeta": 1}


def test_anti_entropy_converges_a_concurrent_loser_without_a_read(tmp_path, config):
    db = build_store(tmp_path, config)
    db.put("k", "one")
    order = list(db.replicas_for("k"))
    shard = db.shard_of("k")
    db.nodes[order[1]].store(shard).put("k", "from-zeta", writer="zeta")
    db.nodes[order[2]].store(shard).put("k", "from-alpha", writer="alpha")
    report = converge(db, "k")
    assert report.repaired == ["k"]
    held = versions(db, "k")
    assert len(set(held)) == 1, held
    assert held[0][2] == "from-zeta"
    assert db.current_generation("k") == 2
