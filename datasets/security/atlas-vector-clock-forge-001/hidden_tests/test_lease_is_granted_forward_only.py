"""ADR-0003, second symptom: the lease book moves forward only.

A holder offering a generation **at or below** the one on record is refused with
the stale-generation error, whichever path it arrived by. `INC-1204` is the
earlier occurrence of this hole; what it records is that the refusal has to keep
the lease exactly where it was, and that a replica which is behind is brought
level by a read, not by a lease that lies for it.
"""

from __future__ import annotations

import pytest

KEY = "acct:7"


def book(*, generation_check: str = "strict"):
    from atlas.fencing import FenceBook
    from atlas.membership import Membership

    membership = Membership(3)
    for worker in ("w-a", "w-b", "w-c"):
        membership.add(worker)
    return FenceBook(membership, generation_check=generation_check)


def state(fence):
    lease = fence.lease(KEY)
    return None if lease is None else (lease.holder, lease.generation)


def test_a_take_over_at_the_generation_on_record_is_refused():
    from atlas.errors import StaleGenerationError

    fence = book()
    fence.advance_lease(KEY, "w-a", 1)
    fence.advance_lease(KEY, "w-b", 2)
    with pytest.raises(StaleGenerationError):
        fence.advance_lease(KEY, "w-a", 2)


def test_a_take_over_below_the_generation_on_record_is_refused():
    from atlas.errors import StaleGenerationError

    fence = book()
    fence.advance_lease(KEY, "w-b", 5)
    with pytest.raises(StaleGenerationError):
        fence.advance_lease(KEY, "w-a", 4)


def test_a_refused_take_over_leaves_the_lease_exactly_where_it_was():
    """INC-1204: "the lease keeps its holder and its generation"."""
    from atlas.errors import StaleGenerationError

    fence = book()
    fence.advance_lease(KEY, "w-b", 2)
    for stale in (2, 1, 0):
        with pytest.raises(StaleGenerationError):
            fence.advance_lease(KEY, "w-a", stale)
    assert state(fence) == ("w-b", 2)


def test_a_refused_take_over_does_not_stop_the_key_moving_forward():
    from atlas.errors import StaleGenerationError

    fence = book()
    fence.advance_lease(KEY, "w-b", 2)
    with pytest.raises(StaleGenerationError):
        fence.advance_lease(KEY, "w-a", 2)
    assert fence.advance_lease(KEY, "w-c", 3).holder == "w-c"
    assert state(fence) == ("w-c", 3)


def test_a_take_over_strictly_ahead_is_granted_and_the_holder_is_recorded():
    fence = book()
    assert fence.advance_lease(KEY, "w-a", 1).generation == 1
    lease = fence.advance_lease(KEY, "w-b", 9)
    assert (lease.holder, lease.generation, lease.epoch) == ("w-b", 9, 3)
    assert fence.current_generation(KEY) == 9


def test_a_key_with_no_lease_on_record_is_granted_whatever_it_names():
    fence = book()
    assert fence.advance_lease("brand:new", "w-a", 7).generation == 7
    assert fence.advance_lease("brand:zero", "w-a", 0).generation == 0


def test_a_released_key_can_be_granted_again_at_the_generation_it_was_left_at():
    """INC-1202 is the trap: an absent lease is not a lease at generation N."""
    fence = book()
    fence.advance_lease(KEY, "w-a", 4)
    fence.release(KEY)
    assert fence.lease(KEY) is None
    assert fence.advance_lease(KEY, "w-b", 4).holder == "w-b"
    assert state(fence) == ("w-b", 4)


def test_the_permissive_mode_relaxes_the_write_check_not_the_lease_book():
    from atlas.errors import StaleGenerationError

    fence = book(generation_check="permissive")
    fence.advance_lease(KEY, "w-b", 4)
    fence.check_write(KEY, writer="w-c", offered_generation=3, planned_epoch=3)
    with pytest.raises(StaleGenerationError):
        fence.advance_lease(KEY, "w-a", 4)
    assert state(fence) == ("w-b", 4)


def test_a_long_take_over_race_never_grants_one_generation_twice():
    from atlas.errors import StaleGenerationError

    fence = book()
    granted: list[int] = []
    offered = [1, 1, 2, 2, 3, 2, 4, 4, 4, 5]
    for step, generation in enumerate(offered):
        holder = f"w-{chr(ord('a') + (step % 3))}"
        expected = generation > (granted[-1] if granted else 0)
        if not expected:
            with pytest.raises(StaleGenerationError):
                fence.advance_lease(KEY, holder, generation)
            continue
        fence.advance_lease(KEY, holder, generation)
        granted.append(generation)
    assert granted == sorted(set(granted)) == [1, 2, 3, 4, 5]
    assert fence.current_generation(KEY) == 5
