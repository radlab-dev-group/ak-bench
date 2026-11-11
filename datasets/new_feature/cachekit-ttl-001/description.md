# Implement `TTLCache` from its specification

`TTLCache` in `src/cachekit/ttl.py` is declared, documented and tested,
but its body raises `NotImplementedError`. Write it.

The full contract — expiry, recency, and what a `put` reclaims first — is
in the module's docstring. Read it before writing a line of code; it is
the specification, and the evaluation measures against it.

## The short version

- Time is logical: every operation takes an explicit `now`. There is no
  wall clock.
- An entry put at `now` expires at `now + ttl`. It is valid while
  `now < expires_at` and expired when `now >= expires_at`: at the expiry
  instant itself the entry is already gone.
- `get(key, now)` returns the value, or `None` when the key is absent or
  expired. Reading an expired entry removes it. A successful read makes
  the key the most recently used one.
- `put(key, value, now)` first purges every expired entry as of `now`,
  then inserts or updates the key (an update refreshes recency and the
  expiry), and finally evicts least recently used entries while over
  capacity. Expired entries are always reclaimed before a live entry is
  evicted.
- `purge(now)` removes every expired entry and returns how many were
  removed. `len(cache)` counts the entries currently stored; an expired
  entry counts until it is purged, read, or passed over by a `put`.
- A non-positive `capacity` or `ttl` raises `ValueError`.

## Examples

| call | result |
| --- | --- |
| `put("a", 1, now=0)`, `get("a", now=9)` with `ttl=10` | `1` |
| `put("a", 1, now=0)`, `get("a", now=10)` with `ttl=10` | `None` (expired) |
| capacity 2, `put a@0, put b@0, put c@10` with `ttl=10` | `a` and `b` purged, `c` stored, nothing live evicted |

## Boundaries

- Implement it in `src/cachekit/ttl.py`; the public API of `cachekit`
  stays as it is.
- Do not modify the repository test suite under `tests/` and do not add
  third-party dependencies — the standard library is enough, and no
  threads or wall-clock time.
- The repository's own test suite (`pytest`) has to stay green, so the
  `lru` module and its behaviour must keep working.
