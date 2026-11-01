"""The invariant a developer can be told about, without the exact test cases."""

import pytest

from bookshop.catalog import Catalog, Item
from bookshop.orders import OrderStore, Status
from bookshop.pricing import Line


@pytest.fixture()
def catalog():
    catalog = Catalog()
    catalog.add(Item(sku="DBP", title="Design Beyond Pixels", price_cents=4900, stock_on_hand=10))
    return catalog


def test_a_confirmation_reserves_and_a_cancellation_gives_back(catalog):
    store = OrderStore(catalog)
    order = store.create([Line("DBP", 3, 4900)])
    store.confirm(order.number)
    assert catalog.get("DBP").reserved == 3
    store.cancel(order.number)
    assert catalog.get("DBP").reserved == 0
    assert catalog.get("DBP").stock_available == 10


def test_available_stock_is_always_on_hand_minus_reserved(catalog):
    store = OrderStore(catalog)
    order = store.create([Line("DBP", 4, 4900)])
    store.confirm(order.number)
    item = catalog.get("DBP")
    assert item.stock_available == item.stock_on_hand - item.reserved
