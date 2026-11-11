"""The optimisation, in miniature: correctness plus a comparison budget."""

from __future__ import annotations

from dedupkit import unique


class CountingItem:
    comparisons = 0

    def __init__(self, value):
        self.value = value

    def __hash__(self):
        return hash(self.value)

    def __eq__(self, other):
        CountingItem.comparisons += 1
        return isinstance(other, CountingItem) and self.value == other.value


def test_unique_still_works():
    assert unique([3, 1, 3, 2, 1, 4]) == [3, 1, 2, 4]


def test_unique_is_linear():
    items = [CountingItem(i % 50) for i in range(200)]
    CountingItem.comparisons = 0
    result = unique(items)
    assert [item.value for item in result] == list(range(50))
    assert CountingItem.comparisons < 600
