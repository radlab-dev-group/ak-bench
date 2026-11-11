"""The finished part of the fixture: session behaviour.

These tests pin the behaviour the refactoring must preserve.
"""

from __future__ import annotations

import pytest

from session import add_to_cart, cart_total, login, logout


def test_a_session_accumulates_a_cart():
    login("Ada")
    add_to_cart(500)
    add_to_cart(250)
    assert cart_total() == 750
    logout()
    assert cart_total() == 0


def test_adding_without_a_session_is_refused():
    logout()
    with pytest.raises(ValueError):
        add_to_cart(100)


def test_login_resets_the_cart():
    login("Ada")
    add_to_cart(500)
    login("Bob")
    assert cart_total() == 0
