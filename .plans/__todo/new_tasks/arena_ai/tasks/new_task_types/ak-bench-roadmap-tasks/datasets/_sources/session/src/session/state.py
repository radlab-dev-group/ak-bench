"""Session state in module globals.

``login(user)`` starts a session, ``logout()`` ends it,
``add_to_cart(price_cents)`` adds an item, and ``cart_total()`` returns
the cart total in cents. The state lives in module globals, so every
caller shares one session.
"""

from __future__ import annotations

_user: str | None = None
_cart: list[int] = []


def login(user: str) -> None:
    """Start a session for ``user`` with an empty cart."""
    global _user, _cart
    _user = user
    _cart = []


def logout() -> None:
    """End the session and clear the cart."""
    global _user, _cart
    _user = None
    _cart = []


def add_to_cart(price_cents: int) -> None:
    """Add an item priced ``price_cents`` to the cart."""
    if _user is None:
        raise ValueError("no session: login first")
    _cart.append(price_cents)


def cart_total() -> int:
    """The cart total in cents."""
    return sum(_cart)
