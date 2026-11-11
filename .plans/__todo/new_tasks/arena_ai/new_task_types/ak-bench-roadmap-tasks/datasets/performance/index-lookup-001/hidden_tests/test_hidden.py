"""The index, proven: correctness plus a comparison budget.

A scanning lookup compares the id against every user (hundreds of
comparisons here); a dict lookup needs almost none.
"""

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


def test_user_index_behaviour():
    users = [User(1, "Ada"), User(2, "Bob"), User(3, "Cid")]
    index = UserIndex(users)
    assert index.find(1) == User(1, "Ada")
    assert index.find(3) == User(3, "Cid")
    assert index.find(99) is None
    assert len(index) == 3
    assert UserIndex([]).find(1) is None
    assert len(UserIndex([])) == 0


def test_find_does_not_scan_the_users():
    users = [User(CountingInt(i), f"user{i}") for i in range(500)]
    index = UserIndex(users)
    CountingInt.comparisons = 0
    assert index.find(CountingInt(499)).name == "user499"
    assert index.find(CountingInt(12345)) is None
    assert CountingInt.comparisons < 20, (
        f"{CountingInt.comparisons} comparisons: find still scans"
    )


def test_find_user_still_works():
    users = [User(1, "Ada"), User(2, "Bob")]
    assert find_user(users, 2) == User(2, "Bob")
    assert find_user(users, 99) is None
