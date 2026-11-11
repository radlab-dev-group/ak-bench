"""The refactoring, proven: target structure plus preserved behaviour.

These tests fail on the base commit (the target module does not exist)
and pass once the validation is extracted.
"""

from __future__ import annotations

import pytest

from forms import register_user
from forms.validation import validate_email, validate_name


def test_validate_name_strips_and_refuses_empty():
    assert validate_name(" Ada ") == "Ada"
    with pytest.raises(ValueError):
        validate_name("   ")
    with pytest.raises(ValueError):
        validate_name("")


def test_validate_email_strips_and_checks_the_shape():
    assert validate_email(" ada@example.com ") == "ada@example.com"
    with pytest.raises(ValueError):
        validate_email("ada.example.com")
    with pytest.raises(ValueError):
        validate_email("ada@")
    with pytest.raises(ValueError):
        validate_email("@example.com")
    with pytest.raises(ValueError):
        validate_email("a@b@c")


def test_register_user_behaviour_is_unchanged():
    assert register_user(" Ada ", "ada@example.com", 36) == {
        "name": "Ada",
        "email": "ada@example.com",
        "age": 36,
    }
    with pytest.raises(ValueError):
        register_user("", "ada@example.com", 36)
    with pytest.raises(ValueError):
        register_user("Ada", "bad", 36)
    with pytest.raises(ValueError):
        register_user("Ada", "ada@example.com", 200)
