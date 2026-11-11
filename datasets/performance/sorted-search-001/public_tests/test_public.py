"""The binary search, in miniature: correctness plus a comparison budget."""

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


def test_search_finds_positions():
    assert search_position([1, 3, 5, 7], 5) == 2
    assert search_position([1, 3, 5, 7], 4) == -1
    assert search_position([], 4) == -1


def test_search_is_logarithmic():
    items = [CountingItem(i) for i in range(1000)]
    CountingItem.comparisons = 0
    index = search_position(items, CountingItem(777))
    assert items[index].value == 777
    assert CountingItem.comparisons < 100
    assert find_position([1, 3, 5], 3) == 1
