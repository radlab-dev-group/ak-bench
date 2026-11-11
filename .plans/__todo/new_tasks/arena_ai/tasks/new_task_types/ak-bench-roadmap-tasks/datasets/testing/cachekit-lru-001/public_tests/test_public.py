"""Harness: the test file must pass on the correct code and fail on the
defective code. The defective variant is a one-line mutation of the
fixture, swapped in for a second run."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import cachekit

TEST_REL = Path('tests/test_lru_agent.py')
DEFECTIVE = {'src/cachekit/lru.py': '"""A least-recently-used cache.\n\nThe rules:\n\n1. ``get`` returns the value for a key, or ``None`` when the key is absent.\n   A successful ``get`` makes the key the most recently used one.\n2. ``put`` inserts or updates a key and makes it the most recently used\n   one. When an insert makes the cache larger than its capacity, the least\n   recently used key is evicted, and so on until the cache fits again.\n3. ``key in cache`` and ``len(cache)`` only look: they never change which\n   key is least recently used. ``keys()`` lists the keys from least to most\n   recently used.\n"""\n\nfrom __future__ import annotations\n\nfrom collections import OrderedDict\nfrom typing import Any\n\n\nclass LRUCache:\n    """A fixed-capacity cache that evicts the least recently used key."""\n\n    def __init__(self, capacity: int) -> None:\n        if capacity <= 0:\n            raise ValueError(f"capacity must be positive, got {capacity}")\n        self._capacity = capacity\n        self._data: OrderedDict[Any, Any] = OrderedDict()\n\n    @property\n    def capacity(self) -> int:\n        """The maximum number of entries the cache holds."""\n        return self._capacity\n\n    def get(self, key: Any) -> Any:\n        """The value for ``key``, or ``None``; a hit refreshes recency."""\n        if key not in self._data:\n            return None\n        return self._data[key]\n\n    def put(self, key: Any, value: Any) -> None:\n        """Insert or update ``key``; evict least recently used keys if full."""\n        if key in self._data:\n            self._data.move_to_end(key)\n        self._data[key] = value\n        while len(self._data) > self._capacity:\n            self._data.popitem(last=False)\n\n    def keys(self) -> list[Any]:\n        """The keys from least to most recently used."""\n        return list(self._data.keys())\n\n    def __contains__(self, key: Any) -> bool:\n        return key in self._data\n\n    def __len__(self) -> int:\n        return len(self._data)\n'}

SAMPLE = '"""Tests for cachekit.lru.LRUCache: recency and eviction."""\n\nfrom __future__ import annotations\n\nfrom cachekit import LRUCache\n\n\ndef test_get_refreshes_recency_and_protects_from_eviction():\n    cache = LRUCache(2)\n    cache.put("a", 1)\n    cache.put("b", 2)\n    assert cache.get("a") == 1\n    cache.put("c", 3)\n    assert cache.get("b") is None\n    assert cache.get("a") == 1\n    assert cache.get("c") == 3\n\n\ndef test_put_updates_the_value_and_refreshes_recency():\n    cache = LRUCache(2)\n    cache.put("a", 1)\n    cache.put("b", 2)\n    cache.put("a", 10)\n    cache.put("c", 3)\n    assert cache.get("b") is None\n    assert cache.get("a") == 10\n\n\ndef test_contains_and_len_do_not_refresh_recency():\n    cache = LRUCache(2)\n    cache.put("a", 1)\n    cache.put("b", 2)\n    assert "a" in cache\n    assert len(cache) == 2\n    cache.put("c", 3)\n    assert cache.get("a") is None\n\n\ndef test_keys_are_listed_least_to_most_recently_used():\n    cache = LRUCache(3)\n    cache.put("a", 1)\n    cache.put("b", 2)\n    cache.put("c", 3)\n    cache.get("a")\n    assert cache.keys() == ["b", "c", "a"]\n\n\ndef test_missing_keys_and_capacity():\n    cache = LRUCache(1)\n    assert cache.get("nope") is None\n    cache.put("a", 1)\n    cache.put("b", 2)\n    assert len(cache) == 1\n    assert cache.get("a") is None\n'

def _repo_root() -> Path:
    return Path(cachekit.__file__).resolve().parents[2]


def _run(defective: bool) -> subprocess.CompletedProcess:
    root = _repo_root()
    pass  # the sample is written into the copy below
    tmp = Path(tempfile.mkdtemp(prefix="agent-tests-"))
    work = tmp / "repo"
    shutil.copytree(
        root,
        work,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
    )
    (work / TEST_REL).parent.mkdir(parents=True, exist_ok=True)
    (work / TEST_REL).write_text(SAMPLE)
    if defective:
        for rel, content in DEFECTIVE.items():
            (work / rel).write_text(content)
    env = {**os.environ, "PYTHONPATH": str(work / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(work / TEST_REL)],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_tests_pass_on_the_correct_code():
    result = _run(defective=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_tests_fail_on_the_defective_code():
    result = _run(defective=True)
    assert result.returncode != 0, "the tests pass on defective code: they do not pin the behaviour"
