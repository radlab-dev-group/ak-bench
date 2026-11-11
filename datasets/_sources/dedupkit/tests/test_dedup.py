"""The finished part of the fixture: deduplication behaviour.

These tests pin the behaviour the optimisation must preserve.
"""

from __future__ import annotations

from dedupkit import unique


def test_removes_duplicates_keeping_order():
    assert unique([3, 1, 3, 2, 1, 4]) == [3, 1, 2, 4]


def test_empty_and_singletons():
    assert unique([]) == []
    assert unique([7]) == [7]


def test_all_duplicates_collapse_to_one():
    assert unique([5, 5, 5]) == [5]
