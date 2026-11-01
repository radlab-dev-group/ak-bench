"""The catalogue: items, stock and the reservation an order makes on it.

Stock is a plain integer count. A reservation is not a separate row: it is the
difference between ``stock_on_hand`` and ``stock_available``, kept consistent by
reserving and releasing through this class only.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class UnknownItem(KeyError):
    """An sku the catalogue has never heard of."""


class InsufficientStock(Exception):
    """A reservation larger than what is available."""


@dataclass(frozen=True)
class Item:
    """One sellable thing. ``price_cents`` is the shelf price, tax exclusive."""

    sku: str
    title: str
    price_cents: int
    stock_on_hand: int = 0
    reserved: int = 0

    def __post_init__(self) -> None:
        if self.price_cents < 0:
            raise ValueError(f"price cannot be negative, got {self.price_cents}")
        if self.stock_on_hand < 0 or self.reserved < 0:
            raise ValueError("stock counts cannot be negative")
        if self.reserved > self.stock_on_hand:
            raise ValueError("more stock reserved than on hand")

    @property
    def stock_available(self) -> int:
        return self.stock_on_hand - self.reserved


@dataclass
class Catalog:
    """A dictionary of items with reservation rules."""

    _items: dict[str, Item] = field(default_factory=dict, repr=False)

    def add(self, item: Item) -> None:
        if item.sku in self._items:
            raise ValueError(f"item {item.sku!r} is already in the catalogue")
        self._items[item.sku] = item

    def get(self, sku: str) -> Item:
        try:
            return self._items[sku]
        except KeyError as exc:
            raise UnknownItem(sku) from exc

    def skus(self) -> list[str]:
        return sorted(self._items)

    def reserve(self, sku: str, quantity: int) -> None:
        """Take ``quantity`` off the available stock of ``sku``."""
        if quantity <= 0:
            raise ValueError(f"reservation must be positive, got {quantity}")
        item = self.get(sku)
        if quantity > item.stock_available:
            raise InsufficientStock(f"{sku}: {quantity} wanted, {item.stock_available} available")
        self._items[sku] = _replace(item, reserved=item.reserved + quantity)

    def release(self, sku: str, quantity: int) -> None:
        """Give ``quantity`` back; never below zero and never above the reservation."""
        if quantity <= 0:
            raise ValueError(f"release must be positive, got {quantity}")
        item = self.get(sku)
        if quantity > item.reserved:
            raise ValueError(f"{sku}: cannot release {quantity}, only {item.reserved} reserved")
        self._items[sku] = _replace(item, reserved=item.reserved - quantity)

    def ship_out(self, sku: str, quantity: int) -> None:
        """Move reserved stock out of the building: it leaves both counts."""
        if quantity <= 0:
            raise ValueError(f"shipment must be positive, got {quantity}")
        item = self.get(sku)
        if quantity > item.reserved:
            raise ValueError(f"{sku}: cannot ship {quantity}, only {item.reserved} reserved")
        self._items[sku] = _replace(
            item, stock_on_hand=item.stock_on_hand - quantity, reserved=item.reserved - quantity
        )


def _replace(item: Item, **changes: int) -> Item:
    """A frozen dataclass copy: the catalogue never mutates an item in place."""
    from dataclasses import replace

    return replace(item, **changes)
