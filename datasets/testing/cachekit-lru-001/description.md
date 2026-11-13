# Write tests that pin the LRU recency rules

`src/cachekit/lru.py` implements an LRU cache. Write a pytest suite for
it in `tests/test_lru_agent.py` that would catch a broken recency rule.

The suite will be run three times, against three copies of the
repository:

1. **as it is** — it must pass;
2. **reformatted** — the same code with comments and blank lines added,
   and nothing else; it must still pass. A suite that hashes the
   sources, or compares them with a snapshot, fails here: a comment
   changed the bytes, not the behaviour;
3. **with one behaviour changed** — the one where `get` does not refresh
   recency; it must fail.

Write at least three test functions, and test behaviour: do not import
`hashlib`, `inspect`, `filecmp`, `difflib`, `dis` or `marshal`, and do not
read the files under `src/`.

Cover at least:

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
