"""What a developer can see without the hidden cases: the shape of a plan."""

from datetime import date

import pytest
from stockpile.allocate import Allocation, allocate
from stockpile.errors import InsufficientStock
from stockpile.lots import Lot
from stockpile.stock import Stock

NOW = date(2026, 5, 10)


def a_stock(*lots: Lot) -> Stock:
    stock = Stock()
    for lot in lots:
        stock.receive(lot)
    return stock


def a_lot(lot_id: str, quantity: int, expires: date) -> Lot:
    return Lot(
        lot_id=lot_id,
        sku="YOG",
        warehouse="W1",
        quantity=quantity,
        received_on=date(2026, 1, 1),
        expires_on=expires,
    )


def test_a_request_from_one_lot_is_planned_from_that_lot():
    stock = a_stock(a_lot("L1", 100, date(2026, 6, 1)))
    plan = allocate(stock, "YOG", 40, warehouse="W1", now=NOW)
    assert isinstance(plan, Allocation)
    assert plan.lots() == ["L1"]
    assert plan.total == 40


def test_the_lot_that_expires_first_is_used_first():
    stock = a_stock(
        a_lot("L-late", 100, date(2026, 8, 1)),
        a_lot("L-soon", 10, date(2026, 5, 20)),
    )
    plan = allocate(stock, "YOG", 15, warehouse="W1", now=NOW)
    assert plan.lots() == ["L-soon", "L-late"]
    assert plan.total == 15


def test_an_expired_lot_is_not_part_of_a_plan():
    stock = a_stock(a_lot("L-gone", 100, date(2026, 4, 1)))
    with pytest.raises(InsufficientStock):
        allocate(stock, "YOG", 10, warehouse="W1", now=NOW)


def test_a_request_bigger_than_the_stock_is_refused():
    stock = a_stock(a_lot("L1", 10, date(2026, 6, 1)))
    with pytest.raises(InsufficientStock):
        allocate(stock, "YOG", 11, warehouse="W1", now=NOW)
