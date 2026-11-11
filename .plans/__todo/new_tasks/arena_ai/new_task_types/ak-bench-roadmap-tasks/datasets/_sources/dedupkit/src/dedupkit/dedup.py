"""Removing duplicates, keeping first occurrences."""

from __future__ import annotations

from typing import Any


def unique(items: list[Any]) -> list[Any]:
    """The items with duplicates removed, in first-occurrence order."""
    result: list[Any] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result
