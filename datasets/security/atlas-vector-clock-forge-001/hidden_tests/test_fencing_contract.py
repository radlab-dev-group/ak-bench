"""The rest of SPEC.md §5, so that closing the hole does not open another one.

The generation check is an equality under `strict` and the epoch check runs
first; a commit marker is checked exactly as a write is. A fix that refuses
every take-over passes the ticket and breaks these.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def _workspace() -> Path:
    for candidate in (Path.cwd(), *Path(__file__).resolve().parents):
        if (candidate / "src" / "atlas").is_dir():
            return candidate
    raise RuntimeError("hidden tests run inside a prepared atlas workspace")


def book(*, generation_check: str = "strict"):
    from atlas.fencing import FenceBook
    from atlas.membership import Membership

    membership = Membership(1)
    for name in ("r1", "r2", "r3"):
        membership.add(name)
    return FenceBook(membership, generation_check=generation_check)


def cluster(root: Path):
    from atlas.config import build as build_config
    from atlas.store import AtlasBuilder

    config = build_config(
        path="none.toml",
        env={},
        values={
            "shards": 2,
            "replication_factor": 3,
            "read_consistency": 2,
            "write_consistency": 2,
            "vnodes": 8,
        },
    )
    return AtlasBuilder().config(config).root(root / "cluster").build()


def test_the_generation_check_is_an_equality_in_both_directions():
    from atlas.errors import StaleGenerationError

    fence = book()
    fence.advance_lease("k", "r1", 3)
    fence.check_write("k", writer="r1", offered_generation=3, planned_epoch=1)
    with pytest.raises(StaleGenerationError):
        fence.check_write("k", writer="r2", offered_generation=2, planned_epoch=1)
    with pytest.raises(StaleGenerationError):
        fence.check_write("k", writer="r2", offered_generation=4, planned_epoch=1)


def test_permissive_lets_a_peer_behind_write_and_still_refuses_one_ahead():
    from atlas.errors import StaleGenerationError

    fence = book(generation_check="permissive")
    fence.advance_lease("k", "r1", 3)
    fence.check_write("k", writer="r2", offered_generation=2, planned_epoch=1)
    with pytest.raises(StaleGenerationError):
        fence.check_write("k", writer="r2", offered_generation=4, planned_epoch=1)


def test_the_epoch_check_runs_before_the_generation_check():
    from atlas.errors import EpochMismatchError

    fence = book()
    fence.advance_lease("k", "r1", 3)
    with pytest.raises(EpochMismatchError):
        fence.check_write("k", writer="r2", offered_generation=99, planned_epoch=0)


def test_a_commit_marker_is_checked_exactly_like_a_write():
    from atlas.errors import StaleGenerationError

    fence = book()
    fence.advance_lease("k", "r1", 3)
    fence.acknowledge("k", 3, 1, "r1")
    with pytest.raises(StaleGenerationError):
        fence.acknowledge("k", 2, 1, "r1")


def test_the_fence_and_storage_agree_after_ordinary_writes(tmp_path):
    atlas = cluster(tmp_path)
    first = atlas.put("account:1", {"v": 1})
    second = atlas.put("account:1", {"v": 2})
    assert (first.record.generation, second.record.generation) == (1, 2)
    assert atlas.current_generation("account:1") == atlas.generation_at("account:1") == 2
    assert atlas.fence.lease("account:1").generation == 2


def test_a_replayed_take_over_does_not_split_the_fence_from_storage(tmp_path):
    from atlas.errors import StaleGenerationError

    atlas = cluster(tmp_path)
    atlas.put("account:1", {"v": 1}, writer="worker-old")
    atlas.put("account:1", {"v": 2}, writer="worker-new")
    held = atlas.generation_at("account:1")
    with pytest.raises(StaleGenerationError):
        atlas.fence.advance_lease("account:1", "worker-old", held)
    assert atlas.generation_at("account:1") == held
    assert atlas.current_generation("account:1") == held
    third = atlas.put("account:1", {"v": 3}, writer="worker-new")
    assert third.record.generation == held + 1


def test_the_repository_suite_still_passes():
    root = _workspace()
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_the_architecture_check_still_passes():
    root = _workspace()
    completed = subprocess.run(
        [sys.executable, "tools/check_arch.py"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=300,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(root / "src")},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
