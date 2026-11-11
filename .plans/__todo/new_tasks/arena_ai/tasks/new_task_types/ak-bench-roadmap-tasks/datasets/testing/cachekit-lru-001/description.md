# Write tests that pin the LRU recency rules

`src/cachekit/lru.py` implements an LRU cache. Write a pytest suite for
it in `tests/test_lru_agent.py` that would catch a broken recency rule.

The suite will be run twice: once against the code as it is (it must
pass) and once against a variant where `get` does not refresh recency
(it must fail). Cover at least:

- a `get` making its key most recently used, so the *other* key is
  evicted next;
- `put` updating a value and refreshing recency;
- `in` and `len` never changing recency;
- `keys()` ordering from least to most recently used;
- missing keys and the capacity limit.

## Boundaries

- Write the tests in `tests/test_lru_agent.py`; do not modify `src/` or the
  existing tests under `tests/`.
- Do not add third-party dependencies.
