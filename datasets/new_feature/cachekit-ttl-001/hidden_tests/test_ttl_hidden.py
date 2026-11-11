"""The specification, tested rule by rule.

Every assertion here is a sentence from the docstring of ``TTLCache``.
"""

from __future__ import annotations

import pytest

from cachekit import TTLCache


def test_the_expiry_instant_itself_is_expired():
    cache = TTLCache(capacity=2, ttl=10)
    cache.put("a", 1, now=5)
    assert cache.get("a", now=14) == 1
    assert cache.get("a", now=15) is None


def test_reading_an_expired_entry_removes_it():
    cache = TTLCache(capacity=2, ttl=10)
    cache.put("a", 1, now=0)
    assert cache.get("a", now=10) is None
    assert len(cache) == 0


def test_a_missing_key_reads_as_none():
    cache = TTLCache(capacity=2, ttl=10)
    assert cache.get("missing", now=0) is None
    assert len(cache) == 0


def test_put_purges_expired_entries_before_evicting_a_live_one():
    cache = TTLCache(capacity=2, ttl=10)
    cache.put("a", 1, now=0)
    cache.put("b", 2, now=0)
    cache.put("c", 3, now=10)
    assert len(cache) == 1
    assert cache.get("c", now=10) == 3
    assert cache.get("a", now=10) is None
    assert cache.get("b", now=10) is None


def test_a_live_lru_entry_is_evicted_when_nothing_expired():
    cache = TTLCache(capacity=2, ttl=100)
    cache.put("a", 1, now=0)
    cache.put("b", 2, now=0)
    cache.put("c", 3, now=1)
    assert cache.get("a", now=1) is None
    assert cache.get("b", now=1) == 2
    assert cache.get("c", now=1) == 3


def test_a_successful_read_refreshes_recency():
    cache = TTLCache(capacity=2, ttl=100)
    cache.put("a", 1, now=0)
    cache.put("b", 2, now=0)
    assert cache.get("a", now=1) == 1
    cache.put("c", 3, now=2)
    assert cache.get("a", now=2) == 1
    assert cache.get("b", now=2) is None


def test_updating_a_key_refreshes_its_expiry():
    cache = TTLCache(capacity=2, ttl=10)
    cache.put("a", 1, now=0)
    cache.put("a", 99, now=9)
    assert cache.get("a", now=18) == 99
    assert cache.get("a", now=19) is None


def test_updating_a_key_refreshes_its_recency():
    cache = TTLCache(capacity=2, ttl=100)
    cache.put("a", 1, now=0)
    cache.put("b", 2, now=0)
    cache.put("a", 99, now=1)
    cache.put("c", 3, now=2)
    assert cache.get("a", now=2) == 99
    assert cache.get("b", now=2) is None


def test_purge_removes_only_the_expired_entries():
    cache = TTLCache(capacity=3, ttl=10)
    cache.put("a", 1, now=0)
    cache.put("b", 2, now=5)
    cache.put("c", 3, now=9)
    assert cache.purge(now=10) == 1
    assert cache.get("b", now=10) == 2
    assert cache.get("c", now=10) == 3


def test_an_expired_entry_counts_towards_len_until_it_is_reclaimed():
    cache = TTLCache(capacity=2, ttl=10)
    cache.put("a", 1, now=0)
    assert len(cache) == 1
    assert cache.purge(now=10) == 1
    assert len(cache) == 0


def test_invalid_arguments_are_refused():
    with pytest.raises(ValueError):
        TTLCache(capacity=0, ttl=10)
    with pytest.raises(ValueError):
        TTLCache(capacity=2, ttl=0)
    with pytest.raises(ValueError):
        TTLCache(capacity=-1, ttl=-1)
