# Reading a key does not protect it from eviction

The cache in `src/cachekit` is an LRU cache in `src/cachekit/lru.py`, and
the rules it follows are documented in that module's docstring. Read them
before touching anything.

A successful `get` makes the key the most recently used one, exactly like
a `put` does. When the cache is full, the least recently used key is the
one evicted.

Today, a key that was just read is still evicted as if it had never been
used: reading does not refresh recency, so hot keys are evicted ahead of
keys that were only written earlier.

## What to check

- `LRUCache.get` in `src/cachekit/lru.py`: after a read, the key must be
  the most recently used one, and the next eviction must take a different
  key.
- `put` on an existing key must keep refreshing recency, and `keys()` must
  keep listing keys from least to most recently used.
- Looking without reading (`in`, `len`) must still not change recency.

## Boundaries

- Do not change the capacity rule or the eviction order.
- Do not modify the repository test suite under `tests/`.
- The public API of the `cachekit` package stays as it is.
- The repository's own test suite has to stay green after your change.
