"""The invariant, enforced where the mutation can still hide.

The defect is a missing release, so the tests are written as accounting: every
count after every transition, for both paths to ``cancelled``, and the same
through the HTTP layer where a route could paper over the service.
"""

import pytest

from bookshop.app import create_app
from bookshop.catalog import Catalog, Item
from bookshop.orders import IllegalTransition, OrderStore, Status
from bookshop.pricing import Line


@pytest.fixture()
def catalog():
    catalog = Catalog()
    catalog.add(Item(sku="DBP", title="Design Beyond Pixels", price_cents=4900, stock_on_hand=10))
    catalog.add(Item(sku="TST", title="Testing in Practice", price_cents=2499, stock_on_hand=6))
    return catalog


def test_cancelling_a_confirmed_order_returns_the_reservation(catalog):
    store = OrderStore(catalog)
    order = store.create([Line("DBP", 3, 4900)])
    store.confirm(order.number)
    store.cancel(order.number)
    assert order.status is Status.CANCELLED
    assert catalog.get("DBP").reserved == 0
    assert catalog.get("DBP").stock_available == 10


def test_cancelling_a_confirmed_order_leaves_the_stock_on_hand(catalog):
    store = OrderStore(catalog)
    order = store.create([Line("DBP", 5, 4900)])
    store.confirm(order.number)
    store.cancel(order.number)
    assert catalog.get("DBP").stock_on_hand == 10


def test_every_line_of_a_multi_line_cancellation_is_returned(catalog):
    store = OrderStore(catalog)
    order = store.create([Line("DBP", 2, 4900), Line("TST", 3, 2499)])
    store.confirm(order.number)
    assert catalog.get("DBP").reserved == 2
    assert catalog.get("TST").reserved == 3
    store.cancel(order.number)
    assert catalog.get("DBP").reserved == 0
    assert catalog.get("TST").reserved == 0


def test_two_cancellations_do_not_free_stock_that_was_never_taken(catalog):
    store = OrderStore(catalog)
    first = store.create([Line("DBP", 4, 4900)])
    store.confirm(first.number)
    store.cancel(first.number)
    second = store.create([Line("DBP", 6, 4900)])
    store.confirm(second.number)
    # 10 on hand, 6 reserved for the still-open second order: 4 available
    assert catalog.get("DBP").stock_available == 4
    store.cancel(second.number)
    assert catalog.get("DBP").stock_available == 10


def test_the_available_count_never_exceeds_the_stock_on_hand(catalog):
    store = OrderStore(catalog)
    order = store.create([Line("TST", 6, 2499)])
    store.confirm(order.number)
    store.cancel(order.number)
    item = catalog.get("TST")
    assert item.stock_available == item.stock_on_hand == 6


def test_a_shipped_order_still_cannot_be_cancelled(catalog):
    store = OrderStore(catalog)
    order = store.create([Line("DBP", 1, 4900)])
    store.confirm(order.number)
    store.ship(order.number)
    with pytest.raises(IllegalTransition):
        store.cancel(order.number)


def test_closing_a_shipped_order_changes_no_stock_count(catalog):
    store = OrderStore(catalog)
    order = store.create([Line("DBP", 2, 4900)])
    store.confirm(order.number)
    store.ship(order.number)
    before = catalog.get("DBP")
    store.close(order.number)
    after = catalog.get("DBP")
    assert (after.stock_on_hand, after.reserved) == (before.stock_on_hand - 0, before.reserved)


def test_the_http_route_honours_the_same_rule():
    catalog = Catalog()
    catalog.add(Item(sku="DBP", title="Design Beyond Pixels", price_cents=4900, stock_on_hand=7))
    client = create_app(catalog).test_client()
    created = client.post(
        "/orders", json={"lines": [{"sku": "DBP", "quantity": 5, "unit_price_cents": 4900}]}
    ).json
    client.post(f"/orders/{created['number']}/confirm", json={})
    assert client.post(f"/orders/{created['number']}/cancel", json={}).status_code == 200
    assert client.get("/items/DBP").json["stock_available"] == 7
