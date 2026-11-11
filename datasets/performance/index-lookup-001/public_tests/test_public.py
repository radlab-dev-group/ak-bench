"""The index, in miniature: correctness plus a comparison budget."""

from __future__ import annotations

from indexkit import User, find_user
from indexkit.index import UserIndex


class CountingInt(int):
    comparisons = 0

    def __new__(cls, value):
        return int.__new__(cls, value)

    def __eq__(self, other):
        CountingInt.comparisons += 1
        return int.__eq__(self, other)

    __hash__ = int.__hash__


def test_user_index_finds_users():
    users = [User(1, "Ada"), User(2, "Bob")]
    index = UserIndex(users)
    assert index.find(2) == User(2, "Bob")
    assert index.find(99) is None
    assert len(index) == 2


def test_find_does_not_scan():
    users = [User(CountingInt(i), f"user{i}") for i in range(500)]
    index = UserIndex(users)
    CountingInt.comparisons = 0
    assert index.find(CountingInt(499)).name == "user499"
    assert CountingInt.comparisons < 20
    assert find_user(users, 1) is not None
