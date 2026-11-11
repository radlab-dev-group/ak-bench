"""Tracking stock quantities.

``Inventory.add(name, qty)`` stocks ``qty`` more of ``name``,
``remove(name)`` drops the item, ``quantity(name)`` returns its
quantity (0 when absent), ``total_items()`` sums every quantity, and
``names()`` lists the stocked names sorted. Names must be non-empty
and quantities must not be negative.
"""

from __future__ import annotations


class Inventory:
    """Stock quantities per item name."""

    def __init__(self) -> None:
        self._stock: dict[str, int] = {}

    def add(self, name: str, qty: int) -> None:
        """Stock ``qty`` more of ``name``."""
        if not name.strip():
            raise ValueError("name must not be empty")
        if qty < 0:
            raise ValueError("qty must not be negative")
        self._stock[name] = self._stock.get(name, 0) + qty

    def remove(self, name: str) -> None:
        """Drop ``name`` from the stock."""
        self._stock.pop(name, None)

    def quantity(self, name: str) -> int:
        """The quantity of ``name``, or 0 when absent."""
        return self._stock.get(name, 0)

    def total_items(self) -> int:
        """The sum of every quantity."""
        return sum(self._stock.values())

    def names(self) -> list[str]:
        """The stocked names, sorted."""
        return sorted(self._stock)
