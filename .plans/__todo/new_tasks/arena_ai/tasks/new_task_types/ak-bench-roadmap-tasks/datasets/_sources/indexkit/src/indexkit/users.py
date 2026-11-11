"""Users and a linear lookup."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    """A user: an id and a name."""

    user_id: int
    name: str


def find_user(users: list[User], user_id: int) -> User | None:
    """The user with ``user_id``, or ``None``; scans the list."""
    for user in users:
        if user.user_id == user_id:
            return user
    return None
