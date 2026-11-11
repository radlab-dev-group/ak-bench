"""The target structure, in miniature: Session exists and is independent."""

from __future__ import annotations

from session import add_to_cart, cart_total, login, logout
from session.store import Session


def test_two_sessions_are_independent():
    first = Session()
    second = Session()
    first.login("Ada")
    first.add_to_cart(500)
    assert first.cart_total() == 500
    assert second.cart_total() == 0


def test_the_module_functions_still_work():
    login("Ada")
    add_to_cart(250)
    assert cart_total() == 250
    logout()
