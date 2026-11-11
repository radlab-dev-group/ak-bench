"""Caches: a plain LRU cache and a TTL cache on logical time."""

from cachekit.lru import LRUCache
from cachekit.ttl import TTLCache

__all__ = [
    "LRUCache",
    "TTLCache",
]
