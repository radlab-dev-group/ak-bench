"""A linear search over a sorted list."""

from __future__ import annotations

from typing import Any


def find_position(items: list[Any], target: Any) -> int:
    """The index of ``target`` in the sorted ``items``, or -1."""
    for index, item in enumerate(items):
        if item == target:
            return index
        if item > target:
            return -1
    return -1
