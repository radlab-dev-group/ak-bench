"""The examples a developer is given: the shape of the contract, not its edges.

They fail on the base commit (the feature is missing) and pass once it is
implemented. They are a subset of the contract, not the whole of it.
"""

from __future__ import annotations

from cachekit import TTLCache


def test_an_entry_is_readable_before_it_expires():
    cache = TTLCache(capacity=2, ttl=10)
    cache.put("a", 1, now=0)
    assert cache.get("a", now=9) == 1


def test_an_entry_is_gone_at_its_expiry_instant():
    cache = TTLCache(capacity=2, ttl=10)
    cache.put("a", 1, now=0)
    assert cache.get("a", now=10) is None


def test_purge_reports_how_many_entries_it_removed():
    cache = TTLCache(capacity=3, ttl=10)
    cache.put("a", 1, now=0)
    cache.put("b", 2, now=5)
    assert cache.purge(now=10) == 1
    assert cache.purge(now=10) == 0
    assert len(cache) == 1
