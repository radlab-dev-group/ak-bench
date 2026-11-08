"""Witness scenarios for the one regression of atlas-drift-002.

The defect is in the module that owns the generation check: the check became
one-sided, so an offer the store does not hold is admitted when it is
*above* the held generation. The scenarios below are the cross-module
combinations the repository suite does not reach: they drive the store
through its own public write path, through a node that bypassed it, and
through the book's own modes, and they pin the documented invariant —
equality — in both directions and in both modes.
"""

import pytest

from atlas.config import build as build_config
from atlas.errors import StaleGenerationError
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


def build_store(tmp_path, config, name="c", **overrides):
    settings = config if not overrides else make_config(**overrides)
    return AtlasBuilder().config(settings).root(tmp_path / name).build()


def _record(key, value, generation, node, lsn=0):
    return Record.put(
        key,
        value,
        generation=generation,
        vector=VersionVector.single(node, generation),
        writer=node,
        lsn=lsn,
    )


def test_regression_02_fencing_refuses_a_generation_ahead_of_the_store(tmp_path, config):
    """A strict check is an equality. A caller that is ahead is refused, not passed.

    The defect makes the check one-sided: a smaller offer is refused, a larger
    one is accepted. The witness offers a generation the store does not hold
    and expects a refusal under the strict check that the configuration
    carries.
    """

    db = build_store(tmp_path, config)
    first = db.put("k", 1).record
    # The fence is now at generation 1. Offer generation 5: the store has not
    # seen it, so it must refuse. The mutated check only refuses offers below.
    with pytest.raises(StaleGenerationError):
        db.put("k", 2, writer="worker", expected_generation=5)
    # And the value must still be the first write.
    assert db.get("k").value == 1


def test_the_offered_generation_must_match_the_held_one_in_both_directions(tmp_path, config):
    """Equality is two refusals, not one.

    The mutation leaves the below-refusal in place, so a review that only
    probes the direction the store used to refuse sees nothing wrong. The
    grid below pins both directions at once: for every (held, offered) pair
    the strict mode refuses exactly the pairs that differ.
    """

    for held, offered in (
        (0, 0),
        (0, 1),
        (0, 7),
        (3, 0),
        (3, 2),
        (3, 3),
        (3, 4),
        (3, 9),
    ):
        db = build_store(tmp_path / f"{held}-{offered}", config)
        for _ in range(held):
            db.put("k", held)
        assert db.fence.current_generation("k") == held
        if offered == held:
            db.put("k", offered)
            assert db.fence.current_generation("k") == held + 1
        else:
            with pytest.raises(StaleGenerationError):
                db.put("k", offered, expected_generation=offered)
            assert db.fence.current_generation("k") == held


def test_permissive_is_a_narrower_door_not_an_open_one():
    """The mode exists for a peer that is behind. It does not open the store.

    A permissive check admits a *smaller* offer — the catching-up peer — and
    still refuses a *greater* one, because a peer ahead of the store means the
    store has been bypassed. The mutation collapses the two modes into one, so
    the permissive arm of this test is what a review of the strict mode alone
    would never reach. The check is driven on the book itself, because a
    behind-peer commit is a check-level decision: below the fence, a replica
    applies its own equality and there is no mode for it to relax.
    """

    from atlas.fencing import FenceBook
    from atlas.membership import Membership

    def book(mode, held):
        membership = Membership(1)
        membership.add("atlas-0")
        instance = FenceBook(membership, generation_check=mode)
        if held:
            instance.grant("k", "atlas-0", held)
        return instance

    for held in (0, 1, 4):
        permissive = book("permissive", held)
        # A smaller offer is the mode's reason to exist: admitted.
        if held:
            permissive.check_write("k", writer="atlas-0", offered_generation=held - 1, planned_epoch=1)
        # The exact offer is admitted.
        permissive.check_write("k", writer="atlas-0", offered_generation=held, planned_epoch=1)
        # A greater offer is still a bypass: refused, in every mode.
        with pytest.raises(StaleGenerationError):
            permissive.check_write("k", writer="atlas-0", offered_generation=held + 1, planned_epoch=1)
        strict = book("strict", held)
        if held:
            with pytest.raises(StaleGenerationError):
                strict.check_write("k", writer="atlas-0", offered_generation=held - 1, planned_epoch=1)
        with pytest.raises(StaleGenerationError):
            strict.check_write("k", writer="atlas-0", offered_generation=held + 1, planned_epoch=1)
        # And the equality itself is admitted under the strict mode too.
        strict.check_write("k", writer="atlas-0", offered_generation=held, planned_epoch=1)


def test_a_node_that_bypassed_the_store_cannot_commit_ahead_of_it(tmp_path, config):
    """The same defect, read through a node instead of a caller.

    A paused replica that caught up on its own is a peer that is ahead of the
    fence: it holds a version the fence has never seen, and the only door its
    work can pass is the check that compares what it offers against what the
    store holds. The mutation opens that door to the right-hand side, which is
    exactly the side a bypassed node stands on. The divergence is driven at
    shard level, the way a paused node would drive it, and the fence must
    refuse it.
    """

    db = build_store(tmp_path, config)
    db.put("k", 1)
    shard = db.shard_of("k")
    held = db.fence.current_generation("k")
    assert held == 1

    # A paused node that replayed one write it was never told about:
    # generation 2, a vector the fence has never seen. It applies it to its
    # own shard directly, which is the only path a node has.
    divergent = sorted(name for name in db.nodes if name != db.owner("k"))[0]
    stray = db.nodes[divergent]
    stray.store(shard).apply_records(
        [_record("k", "stray", held + 1, divergent, lsn=2)], reconcile=True
    )
    assert stray.store(shard).resolve("k").generation == held + 1

    # When that node next tries to commit through the fence, the fence must
    # refuse the offer: it names a generation the store does not hold.
    with pytest.raises(StaleGenerationError):
        db.fence.check_write(
            "k",
            writer="atlas-0",
            offered_generation=held + 1,
            planned_epoch=db.placement.epoch(),
        )


def test_a_fresh_key_refuses_an_offer_above_zero(tmp_path, config):
    """The first write to a key offers generation 0, and only 0.

    The held generation of a key the store has never seen is 0, and the
    equality still applies there: an offer of 1 on a fresh key is an offer
    the store does not hold. The mutation refuses nothing at a fresh key at
    all, which is the case the grid in the test above does not reach because
    the grid always writes first.
    """

    db = build_store(tmp_path, config)
    with pytest.raises(StaleGenerationError):
        db.put("fresh", 1, expected_generation=1)
    # And the store holds nothing for the key: the refused write did not land.
    assert db.get("fresh") is None
    # The correct offer is admitted, which is what keeps a refuse-everything
    # fix from passing this file.
    db.put("fresh", 1)
    assert db.get("fresh").generation == 1


def test_the_correct_offer_is_admitted_and_the_lease_moves(tmp_path, config):
    """The fix is a check, not a wall.

    The equality admits the offer that names exactly what the store holds,
    and the admission moves the lease forward so the next offer must name the
    new generation. A fix that refuses everything passes the refusal tests
    and fails here, which is the difference between a check and a wall.
    """

    db = build_store(tmp_path, config)
    first = db.put("k", "one")
    second = db.put("k", "two")
    assert first.record.generation == 1
    assert second.record.generation == 2
    # The lease follows the writes: the next correct offer is 2, and 1 is now
    # stale in the direction the mutation still refuses, which is the only
    # direction it ever did.
    with pytest.raises(StaleGenerationError):
        db.put("k", "three", expected_generation=1)
    assert db.get("k").value == "two"
