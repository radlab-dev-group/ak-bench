"""The layering, proven: target modules plus preserved behaviour.

These tests fail on the base commit (the target modules do not exist)
and pass once the monolith is split.
"""

from __future__ import annotations

import sqlite3

from shopcore import OrderService
from shopcore.notifier import notify
from shopcore.pricing import price_total
from shopcore.repository import OrderRepository


def test_price_total_follows_the_rules():
    assert price_total([(1000, 2)]) == 2499  # 2000 + 499 shipping
    assert price_total([(10_000, 1)]) == 9500  # 5 % discount, free shipping
    assert price_total([(5000, 1)]) == 5000  # free shipping boundary
    assert price_total([(4999, 1)]) == 5498  # just below free shipping
    assert price_total([]) == 499  # empty order still pays shipping


def test_the_repository_round_trips():
    repo = OrderRepository(sqlite3.connect(":memory:"))
    first = repo.save(2499)
    second = repo.save(9500)
    assert repo.get(first) == 2499
    assert repo.get(second) == 9500
    assert repo.get(999) is None


def test_notify_formats_the_message():
    assert notify(7, 2499) == "Order 7 confirmed: 2499 cents"


def test_place_order_behaviour_is_unchanged():
    service = OrderService()
    assert service.place_order([(1000, 2)]) == {"order_id": 1, "total": 2499}
    assert service.place_order([(10_000, 1)]) == {"order_id": 2, "total": 9500}
    assert service.sent_messages == [
        "Order 1 confirmed: 2499 cents",
        "Order 2 confirmed: 9500 cents",
    ]
