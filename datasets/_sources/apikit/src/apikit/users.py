"""Creating users."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    """A user: name, email and role."""

    name: str
    email: str
    role: str = "user"


def create_user(name: str, email: str, role: str = "user") -> User:
    """Create and return a :class:`User`."""
    return User(name=name, email=email, role=role)
