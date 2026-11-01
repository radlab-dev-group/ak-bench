"""The order lifecycle as the repository itself tests it."""

import pytest

from bookshop.catalog import Catalog, InsufficientStock, Item
from bookshop.orders import IllegalTransition, OrderNotFound, OrderStore, Status
from bookshop.pricing import Line


@pytest.fixture()
def catalog():
    catalog = Catalog()
    catalog.add(Item(sku="DBP", title="Design Beyond Pixels", price_cents=4900, stock_on_hand=10))
    catalog.add(Item(sku="TST", title="Testing in Practice", price_cents=2499, stock_on_hand=4))
    return catalog


@pytest.fixture()
def store(catalog):
    return OrderStore(catalog)


def test_a_new_order_is_open_and_reserves_nothing(store, catalog):
    order = store.create([Line("DBP", 2, 4900)])
    assert order.status is Status.OPEN
    assert catalog.get("DBP").reserved == 0


def test_confirming_reserves_exactly_what_was_ordered(store, catalog):
    order = store.create([Line("DBP", 3, 4900)])
    store.confirm(order.number)
    assert catalog.get("DBP").reserved == 3
    assert catalog.get("DBP").stock_available == 7


def test_confirming_refuses_when_a_line_cannot_be_covered(store):
    order = store.create([Line("TST", 9, 2499)])
    with pytest.raises(IllegalTransition):
        store.confirm(order.number)


def test_shipping_takes_reserved_stock_out(store, catalog):
    order = store.create([Line("DBP", 2, 4900)])
    store.confirm(order.number)
    store.ship(order.number)
    assert catalog.get("DBP").stock_on_hand == 8
    assert catalog.get("DBP").reserved == 0


def test_an_open_order_can_be_cancelled(store, catalog):
    order = store.create([Line("DBP", 1, 4900)])
    store.cancel(order.number)
    assert order.status is Status.CANCELLED
    assert catalog.get("DBP").reserved == 0


def test_a_shipped_order_cannot_be_cancelled(store):
    order = store.create([Line("DBP", 1, 4900)])
    store.confirm(order.number)
    store.ship(order.number)
    with pytest.raises(IllegalTransition):
        store.cancel(order.number)


def test_a_terminal_order_accepts_no_further_move(store):
    order = store.create([Line("DBP", 1, 4900)])
    store.cancel(order.number)
    with pytest.raises(IllegalTransition):
        store.confirm(order.number)


def test_an_unknown_order_number_is_reported(store):
    with pytest.raises(OrderNotFound):
        store.confirm("ORD-9999")


def test_an_empty_order_is_not_created(store):
    with pytest.raises(ValueError):
        store.create([])


def test_the_stock_error_comes_from_the_catalogue_too(catalog):
    with pytest.raises(InsufficientStock):
        catalog.reserve("DBP", 11)
