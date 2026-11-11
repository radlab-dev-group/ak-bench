"""The finished part of the fixture: lookup behaviour.

These tests pin the behaviour the index must preserve.
"""

from __future__ import annotations

from indexkit import User, find_user


def test_find_user_returns_the_match():
    users = [User(1, "Ada"), User(2, "Bob"), User(3, "Cid")]
    assert find_user(users, 2) == User(2, "Bob")


def test_find_user_returns_none_when_absent():
    users = [User(1, "Ada")]
    assert find_user(users, 99) is None
