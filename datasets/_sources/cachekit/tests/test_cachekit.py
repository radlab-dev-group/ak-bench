"""The finished part of the fixture: the plain LRU cache, without reads
in between writes.

The suite deliberately never reads a key and then checks which key was
evicted, so a defect in how reads affect recency is invisible here.
"""

from __future__ import annotations

import pytest

from cachekit import LRUCache


def test_a_cache_needs_a_positive_capacity():
    with pytest.raises(ValueError):
        LRUCache(0)
    with pytest.raises(ValueError):
        LRUCache(-1)


def test_put_and_get_round_trip():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1
    assert cache.get("b") == 2
    assert cache.get("missing") is None


def test_putting_past_capacity_evicts_the_oldest_insert():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert len(cache) == 2
    assert "a" not in cache
    assert "b" in cache
    assert "c" in cache


def test_updating_a_key_replaces_its_value():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("a", 99)
    assert cache.get("a") == 99
    assert len(cache) == 1


def test_keys_are_listed_oldest_first():
    cache = LRUCache(3)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert cache.keys() == ["a", "b", "c"]
