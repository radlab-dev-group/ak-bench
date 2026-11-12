"""The fence, from outside: what a take-over may and may not do.

The first two pass on the build you were given and must keep passing — they are
the trap in this task. The third is the hole.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _source_root() -> Path:
    for candidate in (Path.cwd(), *Path(__file__).resolve().parents):
        if (candidate / "src" / "atlas").is_dir():
            return candidate
    raise RuntimeError("this test runs inside a prepared atlas workspace")


ROOT = _source_root()
sys.path.insert(0, str(ROOT / "src"))

from atlas.errors import StaleGenerationError  # noqa: E402
from atlas.fencing import FenceBook  # noqa: E402
from atlas.membership import Membership  # noqa: E402

KEY = "acct:7"


def book(*, generation_check: str = "strict") -> FenceBook:
    membership = Membership(3)
    for worker in ("w-a", "w-b"):
        membership.add(worker)
    return FenceBook(membership, generation_check=generation_check)


def test_a_take_over_strictly_ahead_is_granted():
    fence = book()
    fence.advance_lease(KEY, "w-a", 1)
    lease = fence.advance_lease(KEY, "w-b", 2)
    assert (lease.holder, lease.generation) == ("w-b", 2)


def test_a_released_key_can_be_taken_at_the_generation_it_was_left_at():
    fence = book()
    fence.advance_lease(KEY, "w-a", 4)
    fence.release(KEY)
    lease = fence.advance_lease(KEY, "w-b", 4)
    assert (lease.holder, lease.generation) == ("w-b", 4)


def test_a_take_over_at_the_generation_on_record_is_refused():
    fence = book()
    fence.advance_lease(KEY, "w-a", 1)
    fence.advance_lease(KEY, "w-b", 2)
    try:
        fence.advance_lease(KEY, "w-a", 2)
    except StaleGenerationError:
        assert (fence.lease(KEY).holder, fence.lease(KEY).generation) == ("w-b", 2)
    else:
        raise AssertionError(
            f"worker w-a took the lease at generation 2, which w-b already holds; "
            f"the lease now says {fence.lease(KEY)}"
        )
