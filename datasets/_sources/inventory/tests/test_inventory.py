"""The finished part of the fixture: inventory behaviour.

These tests pin the behaviour the extraction must preserve.
"""

from __future__ import annotations

import pytest

from inventory import Inventory


def test_add_and_quantity():
    stock = Inventory()
    stock.add("apples", 3)
    stock.add("apples", 2)
    assert stock.quantity("apples") == 5
    assert stock.quantity("pears") == 0


def test_remove_and_totals():
    stock = Inventory()
    stock.add("apples", 3)
    stock.add("pears", 4)
    stock.remove("apples")
    assert stock.names() == ["pears"]
    assert stock.total_items() == 4


def test_invalid_input_is_refused():
    stock = Inventory()
    with pytest.raises(ValueError):
        stock.add("", 1)
    with pytest.raises(ValueError):
        stock.add("apples", -1)
