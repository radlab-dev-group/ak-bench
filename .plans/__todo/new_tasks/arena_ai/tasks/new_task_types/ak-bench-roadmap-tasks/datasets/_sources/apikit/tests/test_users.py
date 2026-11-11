"""The finished part of the fixture: creating a user works.

The role validation has no tests yet; that is part of what the review
should notice.
"""

from __future__ import annotations

from apikit import create_user


def test_create_user_returns_a_user():
    user = create_user("Ada", "ada@example.com")
    assert user.name == "Ada"
    assert user.email == "ada@example.com"
    assert user.role == "user"
