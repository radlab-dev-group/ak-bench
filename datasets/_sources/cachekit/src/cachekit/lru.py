"""A least-recently-used cache.

The rules:

1. ``get`` returns the value for a key, or ``None`` when the key is absent.
   A successful ``get`` makes the key the most recently used one.
2. ``put`` inserts or updates a key and makes it the most recently used
   one. When an insert makes the cache larger than its capacity, the least
   recently used key is evicted, and so on until the cache fits again.
3. ``key in cache`` and ``len(cache)`` only look: they never change which
   key is least recently used. ``keys()`` lists the keys from least to most
   recently used.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any


class LRUCache:
    """A fixed-capacity cache that evicts the least recently used key."""

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError(f"capacity must be positive, got {capacity}")
        self._capacity = capacity
        self._data: OrderedDict[Any, Any] = OrderedDict()

    @property
    def capacity(self) -> int:
        """The maximum number of entries the cache holds."""
        return self._capacity

    def get(self, key: Any) -> Any:
        """The value for ``key``, or ``None``; a hit refreshes recency."""
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def put(self, key: Any, value: Any) -> None:
        """Insert or update ``key``; evict least recently used keys if full."""
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = value
        while len(self._data) > self._capacity:
            self._data.popitem(last=False)

    def keys(self) -> list[Any]:
        """The keys from least to most recently used."""
        return list(self._data.keys())

    def __contains__(self, key: Any) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)
