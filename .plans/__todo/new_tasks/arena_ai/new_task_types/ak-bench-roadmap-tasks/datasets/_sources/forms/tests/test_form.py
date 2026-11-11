"""The finished part of the fixture: registration behaviour.

These tests pin the behaviour the refactoring must preserve.
"""

from __future__ import annotations

import pytest

from forms import register_user


def test_registers_a_valid_user():
    assert register_user(" Ada ", "ada@example.com", 36) == {
        "name": "Ada",
        "email": "ada@example.com",
        "age": 36,
    }


def test_rejects_an_empty_name():
    with pytest.raises(ValueError):
        register_user("   ", "ada@example.com", 36)


def test_rejects_a_bad_email():
    with pytest.raises(ValueError):
        register_user("Ada", "ada.example.com", 36)
    with pytest.raises(ValueError):
        register_user("Ada", "ada@", 36)


def test_rejects_an_out_of_range_age():
    with pytest.raises(ValueError):
        register_user("Ada", "ada@example.com", 151)
