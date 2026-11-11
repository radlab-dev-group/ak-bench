"""The binary search, proven: correctness plus a comparison budget.

A linear scan compares up to 1000 items here; a binary search needs
about 10 comparisons.
"""

from __future__ import annotations

from sortedkit import find_position
from sortedkit.search import find_position as search_position


class CountingItem:
    comparisons = 0

    def __init__(self, value):
        self.value = value

    def __lt__(self, other):
        CountingItem.comparisons += 1
        return self.value < other.value

    def __eq__(self, other):
        return isinstance(other, CountingItem) and self.value == other.value


def test_search_behaviour():
    assert search_position([1, 3, 5, 7], 1) == 0
    assert search_position([1, 3, 5, 7], 7) == 3
    assert search_position([1, 3, 5, 7], 5) == 2
    assert search_position([1, 3, 5, 7], 0) == -1
    assert search_position([1, 3, 5, 7], 8) == -1
    assert search_position([], 4) == -1
    assert search_position([42], 42) == 0
    assert search_position([42], 41) == -1
    # duplicates: any index holding the target is acceptable
    index = search_position([1, 2, 2, 2, 3], 2)
    assert [1, 2, 2, 2, 3][index] == 2


def test_search_is_logarithmic():
    items = [CountingItem(i) for i in range(1000)]
    CountingItem.comparisons = 0
    index = search_position(items, CountingItem(777))
    assert items[index].value == 777
    assert CountingItem.comparisons < 100, (
        f"{CountingItem.comparisons} comparisons: the search is still linear"
    )
    CountingItem.comparisons = 0
    assert search_position(items, CountingItem(10000)) == -1
    assert CountingItem.comparisons < 100


def test_the_package_function_still_works():
    assert find_position([1, 3, 5, 7], 5) == 2
    assert find_position([1, 3, 5, 7], 4) == -1
