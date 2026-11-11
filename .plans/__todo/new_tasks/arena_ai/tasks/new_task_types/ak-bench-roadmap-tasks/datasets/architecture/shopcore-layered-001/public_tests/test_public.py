"""The layers, in miniature: each does its job, the service holds."""

from __future__ import annotations

import sqlite3

from shopcore import OrderService
from shopcore.notifier import notify
from shopcore.pricing import price_total
from shopcore.repository import OrderRepository


def test_each_layer_does_its_job():
    assert price_total([(1000, 2)]) == 2499
    repo = OrderRepository(sqlite3.connect(":memory:"))
    order_id = repo.save(2499)
    assert repo.get(order_id) == 2499
    assert notify(order_id, 2499) == f"Order {order_id} confirmed: 2499 cents"


def test_place_order_still_works():
    service = OrderService()
    assert service.place_order([(1000, 2)]) == {"order_id": 1, "total": 2499}
