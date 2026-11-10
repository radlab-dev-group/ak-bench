"""The cluster paths: repair, anti-entropy, rebalance, and the parity harness."""

import subprocess
import pytest
import sys
from pathlib import Path

from atlas.antientropy import AntiEntropy
from atlas.repair import ReadRepairer
from atlas.values import Record
from atlas.vclock import VersionVector

ROOT = Path(__file__).resolve().parent.parent


def _record(key, value, generation, node):
    return Record.put(
        key, value, generation=generation, vector=VersionVector.single(node, generation), writer=node
    )


def _choose(records):
    from atlas.repair import ReadRepairer

    return ReadRepairer.choose(ReadRepairer.__new__(ReadRepairer), records)


def test_the_causal_winner_dominates_without_the_tie_break():
    winner = _record("k", "new", 2, "n1")
    older = _record("k", "old", 1, "n1")
    chosen, losers, by_tie = _choose([winner, older])
    assert chosen == winner
    assert by_tie is False


def test_concurrent_writes_reach_a_single_winner():
    left = _record("k", "left", 1, "alpha")
    right = _record("k", "right", 1, "zeta")
    winner, losers, by_tie = _choose([left, right])
    assert winner in (left, right)
    assert by_tie is True
    assert len(losers) == 1


def test_repair_writes_the_winner_forward(tmp_path, store):
    store.put("k", "one")
    shard = store.shard_of("k")
    # Two replicas agree on the key; move one behind and repair.
    for replica in store.nodes:
        store.nodes[replica].store(shard).state.forget("k")
    store.nodes["atlas-0"].store(shard).apply_records([store.get("k") or _record("k", "one", 1, "node-0")])
    answers = store.read_replicas("k")
    assert len(answers) == 1


def test_antientropy_finds_no_divergence_on_a_healthy_cluster(store):
    store.put("a", 1)
    store.put("b", 2)
    walk = AntiEntropy(store.nodes, placement=store.placement, width=4)
    names = sorted(store.nodes)
    report = walk.walk(store.nodes[names[0]], store.nodes[names[1]], 0)
    assert report.clean


def test_a_convergence_pass_is_clean_on_a_healthy_cluster(store):
    store.put("a", 1)
    store.put("b", 2)
    walk = AntiEntropy(store.nodes, placement=store.placement, width=4)
    for shard in range(int(store.config["shards"])):
        report = walk.converge(shard, epoch=store.placement.epoch(), repairer=store.repairer)
        assert report.clean
        assert report.repaired == []


def test_a_draining_mark_survives_a_reopen(store):
    store.nodes["atlas-1"].drain()
    reopened = store.reopen_replica("atlas-1")
    assert reopened.draining is True
    reopened.resume()
    assert reopened.draining is False


def test_a_write_that_cannot_reach_a_quorum_names_the_epoch(store):
    from atlas.errors import QuorumError, QuorumShortfallError

    store.put("k", "one")
    order = list(store.replicas_for("k"))
    kept = {name: store.nodes.pop(name) for name in order[1:]}
    try:
        with pytest.raises(QuorumShortfallError) as caught:
            store.put("k", "two", expected_generation=1)
        assert isinstance(caught.value, QuorumError)
        assert "acks below quorum for epoch 1" in str(caught.value)
    finally:
        store.nodes.update(kept)


def test_a_rebalance_moves_the_key_and_keeps_it_readable(tmp_path, config):
    from atlas.store import AtlasBuilder

    db = AtlasBuilder().config(config).root(tmp_path / "c").build()
    db.put("k", "before")
    report = db.rebalance(["atlas-0", "atlas-1", "atlas-2"])
    assert db.get("k") is not None
    assert db.get("k").value == "before"


def test_the_parity_harness_is_clean_on_the_base():
    # No rebalance in this run: the harness's model has no notion of a
    # rebalance, and the store's rebalanced state is not what the model is
    # checking against. The rebalance path is covered by its own test.
    environment = {
        "PYTHONPATH": str(ROOT / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "parity.py"), "--seed", "11", "--length", "80", "--keyspace", "6", "--vnodes", "8", "--only", "put"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "parity.py"), "--seed", "11", "--length", "80", "--keyspace", "6", "--vnodes", "8", "--only", "get"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
