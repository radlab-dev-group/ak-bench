"""The finished part of the fixture: transform behaviour.

These tests pin the behaviour the registry must preserve.
"""

from __future__ import annotations

import pytest

from plugcore import apply


def test_the_builtin_transforms():
    assert apply("upper", "Ada") == "ADA"
    assert apply("lower", "Ada") == "ada"
    assert apply("reverse", "Ada") == "adA"


def test_an_unknown_transform_is_refused():
    with pytest.raises(ValueError):
        apply("shout", "Ada")
