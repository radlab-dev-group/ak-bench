"""The defect, proven from every side the mutation can hide behind.

The hidden tests pass on the base commit and fail once the mutation is
applied; that is the contract of a bug-fix task (docs/DATASETS.md). They
cover reads, updates, lookups that must not refresh, and eviction order
after a sequence of operations.
"""

from __future__ import annotations

from cachekit import LRUCache


def test_a_read_key_survives_the_next_eviction():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1
    cache.put("c", 3)
    assert cache.keys() == ["a", "c"]


def test_repeated_reads_keep_a_key_alive():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")
    cache.put("c", 3)
    cache.get("a")
    cache.put("d", 4)
    assert cache.keys() == ["a", "d"]


def test_reading_the_newest_key_changes_nothing():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("b")
    cache.put("c", 3)
    assert cache.keys() == ["b", "c"]


def test_updating_a_key_also_refreshes_it():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("a", 99)
    cache.put("c", 3)
    assert cache.keys() == ["a", "c"]
    assert cache.get("a") == 99


def test_looking_up_a_key_does_not_refresh_it():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert "a" in cache
    assert len(cache) == 2
    cache.put("c", 3)
    assert cache.keys() == ["b", "c"]


def test_a_missing_read_changes_nothing():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("missing") is None
    cache.put("c", 3)
    assert cache.keys() == ["b", "c"]


def test_eviction_order_after_a_mixed_sequence():
    cache = LRUCache(3)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    cache.get("b")
    cache.put("d", 4)
    assert cache.keys() == ["c", "b", "d"]
    cache.get("c")
    cache.put("e", 5)
    assert cache.keys() == ["d", "c", "e"]


def test_a_capacity_one_cache_evicts_on_every_new_key():
    cache = LRUCache(1)
    cache.put("a", 1)
    assert cache.get("a") == 1
    cache.put("b", 2)
    assert cache.keys() == ["b"]
    assert cache.get("a") is None
