"""A small bookshop service: catalogue, pricing and order lifecycle.

Money is always an integer number of cents. A float never enters the pricing
path, because the benchmark tasks are about the boundaries of rounding and
thresholds, and a float would make the boundary a matter of luck.
"""

from bookshop.catalog import Catalog, InsufficientStock, Item, UnknownItem
from bookshop.orders import IllegalTransition, Order, OrderNotFound, OrderStore, Status
from bookshop.pricing import (
    Basket,
    Line,
    discount_tier,
    price_basket,
    round_cents,
    split_amount,
)

__all__ = [
    "Basket",
    "Catalog",
    "IllegalTransition",
    "InsufficientStock",
    "Item",
    "Line",
    "Order",
    "OrderNotFound",
    "OrderStore",
    "Status",
    "UnknownItem",
    "discount_tier",
    "price_basket",
    "round_cents",
    "split_amount",
]
