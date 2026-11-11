"""A cache whose entries expire after a time-to-live. The rules are in
this docstring; the implementation is the task.

Time is logical: every operation takes an explicit ``now`` (an integer),
and there is no wall clock. ``TTLCache(capacity, ttl)`` holds at most
``capacity`` entries, each living ``ttl`` time units.

- An entry put at ``now`` expires at ``now + ttl``. It is valid while
  ``now < expires_at`` and expired when ``now >= expires_at``: at the
  expiry instant itself the entry is already gone.
- ``get(key, now)`` returns the value, or ``None`` when the key is absent
  or expired. Reading an expired entry removes it. A successful read makes
  the key the most recently used one, exactly as in the LRU cache.
- ``put(key, value, now)`` first purges every expired entry as of ``now``,
  then inserts or updates the key (an update refreshes both recency and
  the expiry, to ``now + ttl``), and finally evicts least recently used
  entries while the cache is over capacity. Expired entries are therefore
  always reclaimed before a live entry is evicted.
- ``purge(now)`` removes every expired entry and returns how many were
  removed.
- ``len(cache)`` counts the entries currently stored. An expired entry
  counts until it is purged, read, or passed over by a ``put``.

``capacity`` and ``ttl`` must be positive; anything else raises
:class:`ValueError`.
"""

from __future__ import annotations

from typing import Any


class TTLCache:
    """A fixed-capacity cache with per-entry expiry on logical time."""

    def __init__(self, capacity: int, ttl: int) -> None:
        raise NotImplementedError("TTLCache is specified in this module and not yet written")

    def get(self, key: Any, now: int) -> Any:
        """The value for ``key`` at ``now``, or ``None``."""
        raise NotImplementedError("TTLCache is specified in this module and not yet written")

    def put(self, key: Any, value: Any, now: int) -> None:
        """Insert or update ``key`` at ``now``, purging expired entries first."""
        raise NotImplementedError("TTLCache is specified in this module and not yet written")

    def purge(self, now: int) -> int:
        """Remove every entry expired at ``now``; return how many were removed."""
        raise NotImplementedError("TTLCache is specified in this module and not yet written")

    def __len__(self) -> int:
        raise NotImplementedError("TTLCache is specified in this module and not yet written")
