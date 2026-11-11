"""The finished part of the fixture: order behaviour.

These tests pin the behaviour the decoupling must preserve. (The
event payload is checked by the task's hidden tests, not here.)
"""

from __future__ import annotations

from eventbus import OrderService


def test_place_order_prices_and_counts():
    service = OrderService()
    assert service.place_order([(1000, 2)]) == {"order_id": 1, "total": 2000}
    assert service.place_order([(500, 1)]) == {"order_id": 2, "total": 500}
