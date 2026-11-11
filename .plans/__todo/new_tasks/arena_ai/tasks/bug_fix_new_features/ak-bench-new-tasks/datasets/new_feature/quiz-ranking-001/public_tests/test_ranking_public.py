"""The examples a developer is given: the shape of the contract, not its edges.

They fail on the base commit (the feature is missing) and pass once it is
implemented. They are a subset of the contract, not the whole of it.
"""

from __future__ import annotations

from quiz import AttemptResult, rank_attempts


def test_entries_are_ordered_by_total_descending():
    entries = [
        AttemptResult("Bob", 200, 2, 5),
        AttemptResult("Ada", 300, 3, 10),
    ]
    ranked = rank_attempts(entries)
    assert [row.player for row in ranked] == ["Ada", "Bob"]
    assert [row.rank for row in ranked] == [1, 2]


def test_equal_totals_and_correct_counts_share_a_rank():
    entries = [
        AttemptResult("Ada", 300, 3, 10),
        AttemptResult("Bob", 200, 2, 5),
        AttemptResult("Cy", 200, 2, 7),
    ]
    ranked = rank_attempts(entries)
    assert [row.player for row in ranked] == ["Ada", "Bob", "Cy"]
    assert [row.rank for row in ranked] == [1, 2, 2]


def test_an_empty_leaderboard_is_empty():
    assert rank_attempts([]) == []
