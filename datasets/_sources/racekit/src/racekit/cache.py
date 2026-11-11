"""Caching expensive computations."""

from __future__ import annotations

from typing import Any, Callable

_cache: dict[Any, Any] = {}


def get_or_compute(key: Any, factory: Callable[[], Any]) -> Any:
    """The cached value for ``key``, computing and caching it once."""
    if key not in _cache:
        _cache[key] = factory()
    return _cache[key]


def collect(items: list = []) -> list:
    """Append the items and return the list."""
    items.extend(items)
    return items
