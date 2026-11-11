"""The target structure, in miniature: helpers exist and behaviour holds."""

from __future__ import annotations

from forms import register_user
from forms.validation import validate_email, validate_name


def test_the_helpers_enforce_the_rules():
    assert validate_name(" Ada ") == "Ada"
    assert validate_email("ada@example.com") == "ada@example.com"


def test_register_user_still_works():
    assert register_user("Ada", "ada@example.com", 36)["name"] == "Ada"
