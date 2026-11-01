"""Order lifecycle: a state machine with one transition table.

Statuses move in one direction only::

    open -> confirmed -> shipped -> closed
      \\         \\
       -> cancelled <-

``cancelled`` and ``closed`` are terminal. A transition that is not in the table
raises :class:`IllegalTransition`; it is never silently ignored, because an
order that quietly refused to move is worse than an exception.

Confirming reserves the stock a basket needs, all of it or none of it. Shipping
moves that stock out of the catalogue. Cancelling gives reserved stock back.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import Enum

from bookshop.catalog import Catalog
from bookshop.pricing import Basket, Line, price_basket


class Status(str, Enum):
    OPEN = "open"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class OrderNotFound(KeyError):
    """An order number the store does not hold."""


class IllegalTransition(Exception):
    """A move the state machine does not allow from the current status."""


#: where each status is allowed to go
TRANSITIONS: dict[Status, frozenset[Status]] = {
    Status.OPEN: frozenset({Status.CONFIRMED, Status.CANCELLED}),
    Status.CONFIRMED: frozenset({Status.SHIPPED, Status.CANCELLED}),
    Status.SHIPPED: frozenset({Status.CLOSED}),
    Status.CLOSED: frozenset(),
    Status.CANCELLED: frozenset(),
}


@dataclass
class Order:
    """One order, its lines and the status it is in."""

    number: str
    lines: list[Line]
    status: Status = Status.OPEN
    basket: Basket | None = None
    events: list[str] = field(default_factory=list, repr=False)

    @property
    def total_cents(self) -> int:
        if self.basket is None:
            return price_basket(self.lines).total_cents
        return self.basket.total_cents


class OrderStore:
    """Orders in memory, with the catalogue they reserve stock against."""

    def __init__(self, catalog: Catalog, *, start: int = 1) -> None:
        self.catalog = catalog
        self._numbers = itertools.count(start)
        self._orders: dict[str, Order] = {}

    def create(self, lines: list[Line]) -> Order:
        """A new order in status ``open``; nothing is reserved yet."""
        if not lines:
            raise ValueError("an order needs at least one line")
        number = f"ORD-{next(self._numbers):04d}"
        order = Order(number=number, lines=list(lines))
        order.events.append("created")
        self._orders[number] = order
        return order

    def get(self, number: str) -> Order:
        try:
            return self._orders[number]
        except KeyError as exc:
            raise OrderNotFound(number) from exc

    def numbers(self) -> list[str]:
        return sorted(self._orders)

    def confirm(self, number: str, voucher_cents: int = 0) -> Order:
        """Price the basket and reserve every line, or leave the order untouched."""
        order = self.get(number)
        self._require(order, Status.CONFIRMED)
        wanted: dict[str, int] = {}
        for line in order.lines:
            wanted[line.sku] = wanted.get(line.sku, 0) + line.quantity
        missing = [
            f"{sku}: {quantity} wanted, {self.catalog.get(sku).stock_available} available"
            for sku, quantity in sorted(wanted.items())
            if quantity > self.catalog.get(sku).stock_available
        ]
        if missing:
            raise IllegalTransition("stock is not available for every line: " + "; ".join(missing))
        for sku, quantity in sorted(wanted.items()):
            self.catalog.reserve(sku, quantity)
        order.basket = price_basket(order.lines, voucher_cents)
        order.status = Status.CONFIRMED
        order.events.append("confirmed")
        return order

    def ship(self, number: str) -> Order:
        """Ship a confirmed order: its reserved stock leaves the catalogue."""
        order = self.get(number)
        self._require(order, Status.SHIPPED)
        for line in order.lines:
            self.catalog.ship_out(line.sku, line.quantity)
        order.status = Status.SHIPPED
        order.events.append("shipped")
        return order

    def cancel(self, number: str) -> Order:
        """Cancel an open or confirmed order, returning any reserved stock."""
        order = self.get(number)
        self._require(order, Status.CANCELLED)
        if order.status is Status.CONFIRMED:
            for line in order.lines:
                self.catalog.release(line.sku, line.quantity)
        order.status = Status.CANCELLED
        order.events.append("cancelled")
        return order

    def close(self, number: str) -> Order:
        """Close a shipped order. Nothing left to do but record it."""
        order = self.get(number)
        self._require(order, Status.CLOSED)
        order.status = Status.CLOSED
        order.events.append("closed")
        return order

    def _require(self, order: Order, target: Status) -> None:
        if target not in TRANSITIONS[order.status]:
            raise IllegalTransition(
                f"order {order.number} is {order.status.value} and cannot become {target.value}"
            )
