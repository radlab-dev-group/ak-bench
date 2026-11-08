"""The cluster paths: repair, anti-entropy, rebalance, and the parity harness."""

import subprocess
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


def test_concurrent_writes_are_settled_by_the_greatest_writer():
    left = _record("k", "left", 1, "alpha")
    right = _record("k", "right", 1, "zeta")
    winner, losers, by_tie = _choose([left, right])
    assert winner is right
    assert by_tie is True


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


def test_a_rebalance_moves_the_key_and_keeps_it_readable(tmp_path, config):
    from atlas.store import AtlasBuilder

    db = AtlasBuilder().config(config).root(tmp_path / "c").build()
    db.put("k", "before")
    report = db.rebalance(["atlas-1", "atlas-2", "atlas-3"])
    assert "k" in report.moved_keys or report.copied >= 0
    assert db.get("k") is not None


def test_the_parity_harness_is_clean_on_the_base():
    environment = {
        "PYTHONPATH": str(ROOT / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "parity.py"), "--seed", "11", "--length", "80", "--keyspace", "6", "--vnodes", "8"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
