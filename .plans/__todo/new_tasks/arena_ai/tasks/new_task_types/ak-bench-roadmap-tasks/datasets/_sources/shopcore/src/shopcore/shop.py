"""Placing orders, end to end.

``OrderService.place_order(items)`` takes ``(unit_price_cents,
quantity)`` pairs, prices the order (5 % discount from 10 000 cents,
free shipping from 5 000 cents, otherwise 499 cents), stores it in
sqlite, records a confirmation message, and returns a dict with
``order_id`` and ``total``.
"""

from __future__ import annotations

import sqlite3
from decimal import ROUND_HALF_UP, Decimal


class OrderService:
    """Prices, stores and announces orders."""

    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        self._conn = conn or sqlite3.connect(":memory:")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, total INTEGER)"
        )
        self.sent_messages: list[str] = []

    def place_order(self, items: list[tuple[int, int]]) -> dict:
        """Price, store and announce the order; return its id and total."""
        subtotal = sum(price * qty for price, qty in items)
        if subtotal >= 10_000:
            discount = int(
                (Decimal(subtotal) * Decimal("0.05")).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
        else:
            discount = 0
        shipping = 0 if subtotal >= 5_000 else 499
        total = subtotal - discount + shipping
        cursor = self._conn.execute("INSERT INTO orders (total) VALUES (?)", (total,))
        order_id = cursor.lastrowid
        self.sent_messages.append(f"Order {order_id} confirmed: {total} cents")
        return {"order_id": order_id, "total": total}
