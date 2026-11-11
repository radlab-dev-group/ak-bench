"""Placing orders and publishing them on the bus.

``OrderService.place_order(items)`` prices the order (the sum of
``unit_price * quantity``), publishes an order-placed event on the
bus, and returns a dict with ``order_id`` and ``total``.
"""

from __future__ import annotations

from eventbus.bus import EventBus


class OrderService:
    """Places orders and announces them on the bus."""

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus = bus or EventBus()
        self._next_id = 1

    def place_order(self, items: list[tuple[int, int]]) -> dict:
        """Price the order, publish it, and return its id and total."""
        total = sum(price * qty for price, qty in items)
        order_id = self._next_id
        self._next_id += 1
        self._bus.publish({"order_id": order_id, "total": total})
        return {"order_id": order_id, "total": total}
