"""The same rules through HTTP, so a route cannot disagree with the service."""

from bookshop.app import create_app, default_catalog
from bookshop.catalog import Catalog, Item


def client_with(stock=10):
    catalog = Catalog()
    catalog.add(Item(sku="DBP", title="Design Beyond Pixels", price_cents=4900, stock_on_hand=stock))
    return create_app(catalog).test_client()


def test_health_answers():
    assert client_with().get("/health").json == {"status": "ok"}


def test_items_are_listed_with_what_is_available():
    body = client_with().get("/items").json
    assert body["items"][0]["sku"] == "DBP"
    assert body["items"][0]["stock_available"] == 10


def test_an_unknown_item_is_a_404():
    assert client_with().get("/items/NOPE").status_code == 404


def test_a_quote_carries_the_pricing_shape():
    body = client_with().post("/quote", json={"lines": [{"sku": "DBP", "quantity": 2,
                                                        "unit_price_cents": 4900}]}).json
    assert body["subtotal_cents"] == 9800
    assert set(body) >= {"discount_cents", "tax_cents", "total_cents"}


def test_an_order_can_be_placed_and_confirmed_over_http():
    client = client_with()
    created = client.post("/orders", json={"lines": [{"sku": "DBP", "quantity": 2,
                                                     "unit_price_cents": 4900}]})
    assert created.status_code == 201
    number = created.json["number"]
    confirmed = client.post(f"/orders/{number}/confirm", json={})
    assert confirmed.json["status"] == "confirmed"
    assert confirmed.json["total_cents"] > 0


def test_confirming_without_stock_is_a_conflict():
    client = client_with(stock=1)
    created = client.post("/orders", json={"lines": [{"sku": "DBP", "quantity": 5,
                                                     "unit_price_cents": 4900}]}).json
    assert client.post(f"/orders/{created['number']}/confirm", json={}).status_code == 409


def test_a_bad_payload_is_a_400():
    assert client_with().post("/orders", json={"lines": [{"quantity": 1}]}).status_code == 400


def test_an_unknown_order_is_a_404():
    assert client_with().post("/orders/ORD-9999/confirm", json={}).status_code == 404
