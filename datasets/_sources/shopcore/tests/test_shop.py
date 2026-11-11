"""The finished part of the fixture: order behaviour.

These tests pin the behaviour the layering must preserve.
"""

from __future__ import annotations

from shopcore import OrderService


def test_a_small_order_pays_shipping():
    service = OrderService()
    assert service.place_order([(1000, 2)]) == {"order_id": 1, "total": 2499}


def test_a_large_order_gets_discount_and_free_shipping():
    service = OrderService()
    assert service.place_order([(10_000, 1)]) == {"order_id": 1, "total": 9500}


def test_orders_get_increasing_ids_and_messages():
    service = OrderService()
    service.place_order([(1000, 1)])
    service.place_order([(1000, 1)])
    assert service.sent_messages == [
        "Order 1 confirmed: 1499 cents",
        "Order 2 confirmed: 1499 cents",
    ]
