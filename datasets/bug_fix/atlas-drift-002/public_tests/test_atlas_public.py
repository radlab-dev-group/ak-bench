"""Visible checks for the fencing invariant. These are not the whole evidence.

They fail on a cluster that has lost the rule and pass on a correct one, and
they are deliberately less surgical than the hidden scenarios: they say which
rule broke, not which line broke it.
"""

import pytest

from atlas.config import build as build_config
from atlas.errors import StaleGenerationError
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


def build_store(tmp_path, name="c", **overrides):
    return AtlasBuilder().config(make_config(**overrides)).root(tmp_path / name).build()


def test_the_generation_check_is_an_equality(tmp_path):
    db = build_store(tmp_path)
    db.put("k", 1)
    with pytest.raises(StaleGenerationError):
        db.put("k", 2, expected_generation=99)


def test_a_stale_offer_is_still_refused(tmp_path):
    db = build_store(tmp_path)
    db.put("k", 1)
    db.put("k", 2)
    with pytest.raises(StaleGenerationError):
        db.put("k", 3, expected_generation=0)


def test_the_matching_offer_is_admitted(tmp_path):
    db = build_store(tmp_path)
    db.put("k", 1)
    db.put("k", 2, expected_generation=1)
    assert db.get("k").value == 2


def test_permissive_admits_a_behind_peer_and_refuses_an_ahead_one():
    from atlas.fencing import FenceBook
    from atlas.membership import Membership

    membership = Membership(1)
    membership.add("atlas-0")
    fence = FenceBook(membership, generation_check="permissive")
    fence.grant("k", "atlas-0", 3)
    fence.check_write("k", writer="atlas-0", offered_generation=2, planned_epoch=1)
    with pytest.raises(StaleGenerationError):
        fence.check_write("k", writer="atlas-0", offered_generation=4, planned_epoch=1)
