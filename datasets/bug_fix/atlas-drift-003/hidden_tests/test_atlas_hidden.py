"""Witness scenarios for the one regression of atlas-drift-003.

The defect is in the module that owns the tie-break between two concurrent
versions: the comparison was flipped, so the smaller writer identifier wins.
The scenarios below are the cross-module combinations the repository suite
does not reach: they pin the direction of the comparison in the module that
owns it, in the module that meets concurrent versions a second time, and in
the cluster paths that write the answer forward — repair and anti-entropy —
which is what makes a wrong direction permanent instead of transient.
"""

import itertools

import pytest

from atlas.config import build as build_config
from atlas.repair import ReadRepairer
from atlas.store import AtlasBuilder
from atlas.values import Record
from atlas.vclock import VersionVector


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


def _record(key, value, generation, node, lsn=0):
    return Record.put(
        key,
        value,
        generation=generation,
        vector=VersionVector.single(node, generation),
        writer=node,
        lsn=lsn,
    )


def _choose(records):
    return ReadRepairer.choose(ReadRepairer.__new__(ReadRepairer), records)


def test_regression_04_concurrent_writes_resolve_to_the_greatest_writer(tmp_path, config):
    """The tie-break is descending writer identifier, in one direction.

    The defect flips it to ascending. The witness constructs two concurrent
    versions with writers on opposite ends of the identifier space and
    requires the greater one to win.
    """

    left = _record("k", "left", 1, "aaa", lsn=1)
    right = _record("k", "right", 1, "zzz", lsn=2)
    winner, losers, by_tie = ReadRepairer.choose(ReadRepairer.__new__(ReadRepairer), [left, right])
    assert by_tie is True
    assert winner is right, (
        f"the concurrent write resolved to {winner.value!r}; the documented tie-break "
        "is the greatest writer identifier, which is 'zzz'"
    )


def test_the_direction_is_pinned_over_the_whole_identifier_space():
    """The rule is a direction, and a direction is pinned by many pairs.

    A single pair with writers on opposite ends is one data point. The grid
    below checks the comparison against every pair of writer names in a
    small space, in both candidate orders, and requires the greater name to
    win in every case. A flipped comparison fails half the grid in each
    order; a fix that sorts by something else fails the whole grid.
    """

    writers = ["alpha", "beta", "gamma", "delta", "zeta", "node-0", "node-1"]
    for a, b in itertools.permutations(writers, 2):
        left = _record("k", a, 1, a)
        right = _record("k", b, 1, b)
        for candidates in ([left, right], [right, left]):
            winner, _losers, by_tie = _choose(candidates)
            assert by_tie is True, (a, b)
            expected = a if a > b else b
            assert winner.value == expected, (
                f"writers {a!r} and {b!r} resolved to {winner.value!r}; "
                f"the documented tie-break is the greatest, {expected!r}"
            )


def test_a_three_way_convergence_reaches_the_greatest_name_in_any_order():
    """The winner of a three-way tie is independent of who arrives first.

    Three concurrent versions, the same vector shape, three different
    writers. The documented rule names one winner — the greatest writer —
    and the comparison must reach it whichever way the candidates are
    ordered, because replicas meet the same three versions in different
    orders.
    """

    alpha = _record("k", "alpha", 1, "alpha")
    gamma = _record("k", "gamma", 1, "gamma")
    zeta = _record("k", "zeta", 1, "zeta")
    for order in itertools.permutations((alpha, gamma, zeta)):
        winner, losers, by_tie = _choose(list(order))
        assert by_tie is True
        assert winner is zeta, f"order {tuple(r.value for r in order)} resolved to {winner.value!r}"
        assert sorted(loser.value for loser in losers) == ["alpha", "gamma"]


def test_the_causal_winner_still_dominates_the_tie_break():
    """The tie-break is for ties. A version that dominates must win on its own.

    The comparison is consulted only between versions that are concurrent.
    A version that strictly dominates the other wins before any name is
    compared, whatever the names say. A fix that reaches for the name
    unconditionally passes the tie tests and fails here, which is the
    difference between the documented rule and a sort.
    """

    # Same writer, higher generation: dominance, no tie-break.
    older = _record("k", "old", 1, "zzz", lsn=1)
    newer = _record("k", "new", 2, "zzz", lsn=2)
    winner, _losers, by_tie = _choose([older, newer])
    assert winner is newer
    assert by_tie is False

    # Different writers, one vector above the other: dominance still wins.
    below = _record("k", "below", 1, "aaa")
    above = _record("k", "above", 1, "bbb")
    above = Record.put(
        "k",
        "above",
        generation=2,
        vector=VersionVector.new({"aaa": 1, "bbb": 1}),
        writer="bbb",
    )
    winner, _losers, by_tie = _choose([below, above])
    assert winner is above
    assert by_tie is False


def test_repair_writes_the_documented_winner_forward(tmp_path, config):
    """The cluster path that makes a wrong direction permanent.

    Two replicas hold concurrent versions of one key. Repair reads both,
    chooses the winner, and writes it to every replica that does not already
    hold it. The choice is the whole contract: a flipped comparison makes
    repair write the wrong answer forward to every peer, and the divergence
    is the data from then on.
    """

    db = build_store(tmp_path, config)
    db.put("k", "seed")
    shard = db.shard_of("k")
    names = sorted(db.nodes)
    left_node, right_node = db.nodes[names[0]], db.nodes[names[1]]

    # Two replicas, two concurrent versions of the same key.
    left = _record("k", "left", 1, "alpha", lsn=1)
    right = _record("k", "right", 1, "zeta", lsn=2)
    left_node.store(shard).apply_records([left], reconcile=True)
    right_node.store(shard).apply_records([right], reconcile=True)

    winner, _losers, by_tie = _choose([left, right])
    assert by_tie is True
    assert winner is right, f"repair chose {winner.value!r}; the documented winner is 'right'"

    outcome = db.repairer.repair("k", winner, replicas=names, placement=db.placement)
    # Every replica that did not hold the winner now holds it.
    for name in names:
        held = db.nodes[name].store(shard).resolve("k")
        assert held is not None and held.vector == right.vector, (
            f"replica {name} holds {held.render() if held else None} after repair"
        )


def test_the_digest_walk_names_the_divergence_repair_settles(tmp_path, config):
    """The second module that meets concurrent versions must agree.

    The range-digest walk is the part of anti-entropy that can run here: it
    compares what two shards hold over the same range and names the keys that
    differ. The settlement is the tie-break. If the two modules disagreed —
    if the walk named one winner and the settlement another — the cluster
    would converge on different answers on different replicas. This test
    drives the pair together and requires the settled answer to be the
    documented one.
    """

    from atlas.antientropy import compare_digests, range_digest

    db = build_store(tmp_path, config)
    db.put("k", "seed")
    shard = db.shard_of("k")
    names = sorted(db.nodes)
    left_node, right_node = db.nodes[names[0]], db.nodes[names[1]]

    left = _record("k", "left", 1, "alpha", lsn=1)
    right = _record("k", "right", 1, "zeta", lsn=2)
    left_node.store(shard).apply_records([left], reconcile=True)
    right_node.store(shard).apply_records([right], reconcile=True)

    # The walk sees the divergence: the same key, the same range, different
    # digests on the two shards.
    low, high = "00000000", "\uffff"
    left_digest = range_digest(left_node.store(shard), low, high)
    right_digest = range_digest(right_node.store(shard), low, high)
    assert not compare_digests(left_digest.digest, right_digest.digest)

    # The settlement the walk implies is the tie-break, and the tie-break is
    # the documented direction.
    winner, _losers, by_tie = _choose([left, right])
    assert by_tie is True
    assert winner is right
    # And settling it leaves every walked replica on the same version.
    for name in names[:2]:
        db.nodes[name].store(shard).apply_records([winner], reconcile=True)
    for name in names[:2]:
        assert db.nodes[name].store(shard).resolve("k").vector == right.vector
