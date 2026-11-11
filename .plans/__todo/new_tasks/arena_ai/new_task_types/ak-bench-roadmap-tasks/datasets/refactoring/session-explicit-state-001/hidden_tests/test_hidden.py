"""The refactoring, proven: target structure plus preserved behaviour.

These tests fail on the base commit (the target module does not exist)
and pass once the state is explicit.
"""

from __future__ import annotations

import pytest

from session import add_to_cart, cart_total, login, logout
from session.store import Session


def test_two_sessions_are_independent():
    first = Session()
    second = Session()
    first.login("Ada")
    first.add_to_cart(500)
    second.login("Bob")
    second.add_to_cart(100)
    assert first.cart_total() == 500
    assert second.cart_total() == 100
    first.logout()
    assert first.cart_total() == 0
    assert second.cart_total() == 100


def test_a_session_refuses_adding_without_login():
    session = Session()
    with pytest.raises(ValueError):
        session.add_to_cart(100)


def test_login_resets_the_cart():
    session = Session()
    session.login("Ada")
    session.add_to_cart(500)
    session.login("Bob")
    assert session.cart_total() == 0


def test_the_module_functions_behaviour_is_unchanged():
    login("Ada")
    add_to_cart(500)
    add_to_cart(250)
    assert cart_total() == 750
    logout()
    assert cart_total() == 0
    with pytest.raises(ValueError):
        add_to_cart(100)
