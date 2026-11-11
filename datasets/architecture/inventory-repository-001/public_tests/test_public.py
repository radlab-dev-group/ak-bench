"""The extraction, in miniature: store and validation work, Inventory holds."""

from __future__ import annotations

import pytest

from inventory import Inventory
from inventory.storage import InventoryStore
from inventory.validation import validate_item


def test_the_store_and_validation_work():
    store = InventoryStore()
    store.add("apples", 3)
    assert store.quantity("apples") == 3
    validate_item("apples", 1)
    with pytest.raises(ValueError):
        validate_item("", 1)


def test_inventory_still_works():
    stock = Inventory()
    stock.add("apples", 3)
    assert stock.quantity("apples") == 3
