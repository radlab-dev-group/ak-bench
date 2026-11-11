"""The extraction, proven: target modules plus preserved behaviour.

These tests fail on the base commit (the target modules do not exist)
and pass once storage and validation are extracted.
"""

from __future__ import annotations

import pytest

from inventory import Inventory
from inventory.storage import InventoryStore
from inventory.validation import validate_item


def test_the_store_is_plain_dict_storage():
    store = InventoryStore()
    store.add("apples", 3)
    store.add("apples", 2)
    store.add("pears", 4)
    assert store.quantity("apples") == 5
    assert store.quantity("pears") == 4
    assert store.quantity("plums") == 0
    assert store.total_items() == 9
    assert store.names() == ["apples", "pears"]
    store.remove("apples")
    assert store.quantity("apples") == 0
    assert store.names() == ["pears"]


def test_validate_item_enforces_the_rules():
    assert validate_item("apples", 0) is None
    assert validate_item("apples", 5) is None
    with pytest.raises(ValueError):
        validate_item("", 1)
    with pytest.raises(ValueError):
        validate_item("   ", 1)
    with pytest.raises(ValueError):
        validate_item("apples", -1)


def test_inventory_behaviour_is_unchanged():
    stock = Inventory()
    stock.add("apples", 3)
    stock.add("apples", 2)
    assert stock.quantity("apples") == 5
    stock.add("pears", 4)
    stock.remove("apples")
    assert stock.names() == ["pears"]
    assert stock.total_items() == 4
    with pytest.raises(ValueError):
        stock.add("", 1)
    with pytest.raises(ValueError):
        stock.add("apples", -1)
