"""The HTTP face of the bookshop: a Flask application factory.

The routes are thin. Every rule that matters lives in :mod:`bookshop.pricing`
and :mod:`bookshop.orders`, so an endpoint can be tested through the service
layer or through the test client and reach the same answer.
"""

from __future__ import annotations

from flask import Flask, Response, jsonify, request

from bookshop.catalog import Catalog, InsufficientStock, Item, UnknownItem
from bookshop.orders import IllegalTransition, OrderNotFound, OrderStore
from bookshop.pricing import Line


class UnknownFormat(Exception):
    """A request asked for a representation the service does not produce."""


def create_app(catalog: Catalog | None = None) -> Flask:
    """Build the app, optionally over a catalogue the caller already filled."""
    app = Flask(__name__)
    inventory = catalog if catalog is not None else default_catalog()
    app.extensions["catalog"] = inventory
    app.extensions["orders"] = OrderStore(inventory)

    @app.get("/health")
    def health() -> Response:
        return jsonify(status="ok")

    @app.get("/items")
    def list_items() -> Response:
        catalog_ = app.extensions["catalog"]
        return jsonify(
            items=[
                {
                    "sku": item.sku,
                    "title": item.title,
                    "price_cents": item.price_cents,
                    "stock_available": item.stock_available,
                }
                for item in (catalog_.get(sku) for sku in catalog_.skus())
            ]
        )

    @app.get("/items/<sku>")
    def get_item(sku: str) -> Response:
        try:
            item = app.extensions["catalog"].get(sku)
        except UnknownItem:
            return jsonify(error="unknown item"), 404
        return jsonify(
            sku=item.sku,
            title=item.title,
            price_cents=item.price_cents,
            stock_on_hand=item.stock_on_hand,
            stock_available=item.stock_available,
        )

    @app.post("/quote")
    def quote() -> Response:
        payload = request.get_json(silent=True) or {}
        try:
            lines = [Line(str(l["sku"]), int(l["quantity"]), int(l["unit_price_cents"]))
                     for l in payload.get("lines", [])]
            basket = _price(list(lines), int(payload.get("voucher_cents", 0)))
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify(error=f"bad quote request: {exc}"), 400
        return jsonify(
            subtotal_cents=basket.subtotal_cents,
            discount_cents=basket.discount_cents,
            voucher_cents=basket.voucher_cents,
            taxable_cents=basket.taxable_cents,
            tax_cents=basket.tax_cents,
            total_cents=basket.total_cents,
            tier=str(basket.tier) if basket.tier is not None else None,
        )

    @app.post("/orders")
    def create_order() -> Response:
        payload = request.get_json(silent=True) or {}
        try:
            lines = [Line(str(l["sku"]), int(l["quantity"]), int(l["unit_price_cents"]))
                     for l in payload.get("lines", [])]
            order = app.extensions["orders"].create(list(lines))
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify(error=f"bad order request: {exc}"), 400
        return jsonify(number=order.number, status=order.status.value), 201

    @app.post("/orders/<number>/confirm")
    def confirm_order(number: str) -> Response:
        payload = request.get_json(silent=True) or {}
        try:
            order = app.extensions["orders"].confirm(number, int(payload.get("voucher_cents", 0)))
        except OrderNotFound:
            return jsonify(error="unknown order"), 404
        except (IllegalTransition, InsufficientStock) as exc:
            return jsonify(error=str(exc)), 409
        return jsonify(number=order.number, status=order.status.value,
                       total_cents=order.basket.total_cents)

    @app.post("/orders/<number>/ship")
    def ship_order(number: str) -> Response:
        return _transition(number, "ship")

    @app.post("/orders/<number>/cancel")
    def cancel_order(number: str) -> Response:
        return _transition(number, "cancel")

    @app.get("/orders/<number>")
    def get_order(number: str) -> Response:
        try:
            order = app.extensions["orders"].get(number)
        except OrderNotFound:
            return jsonify(error="unknown order"), 404
        return jsonify(
            number=order.number,
            status=order.status.value,
            total_cents=order.total_cents,
            events=list(order.events),
        )

    def _transition(number: str, action: str) -> Response:
        store = app.extensions["orders"]
        try:
            order = getattr(store, action)(number)
        except OrderNotFound:
            return jsonify(error="unknown order"), 404
        except (IllegalTransition, InsufficientStock) as exc:
            return jsonify(error=str(exc)), 409
        return jsonify(number=order.number, status=order.status.value)

    return app


def default_catalog() -> Catalog:
    """A catalogue small enough to read and big enough to be useful."""
    catalog = Catalog()
    catalog.add(Item(sku="DBP", title="Design Beyond Pixels", price_cents=4900, stock_on_hand=12))
    catalog.add(Item(sku="CLN", title="Cleancut Architecture", price_cents=3950, stock_on_hand=8))
    catalog.add(Item(sku="TST", title="Testing in Practice", price_cents=2499, stock_on_hand=25))
    catalog.add(Item(sku="PRA", title="Pragmatic Retrieval", price_cents=9900, stock_on_hand=2))
    return catalog


def _price(lines: list[Line], voucher_cents: int):  # pragma: no cover - indirection
    """Import late so the pricing module stays the single place rules live."""
    from bookshop.pricing import price_basket

    return price_basket(lines, voucher_cents)
