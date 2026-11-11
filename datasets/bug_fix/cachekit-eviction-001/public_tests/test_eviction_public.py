"""What a developer is told about this defect: a read refreshes recency.

These tests are visible to the agent. They state the rule and probe it at
the edges the hidden tests also care about, so an agent can find the defect
without being handed the exact assertions the evaluation uses.
"""

from __future__ import annotations

from cachekit import LRUCache


def test_a_read_key_survives_the_next_eviction():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1
    cache.put("c", 3)
    assert "a" in cache
    assert "b" not in cache
    assert "c" in cache


def test_a_read_key_becomes_the_most_recently_used():
    cache = LRUCache(3)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    cache.get("a")
    assert cache.keys() == ["b", "c", "a"]
