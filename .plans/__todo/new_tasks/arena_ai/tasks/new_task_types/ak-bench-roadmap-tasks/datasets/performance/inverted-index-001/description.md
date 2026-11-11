# Build an inverted index for document search

`search` in `src/searchkit/scan.py` scans every document for every
query. Add an inverted index so queries answer from the index alone:

- Create `src/searchkit/index.py` with `build_index(docs) -> dict`
  mapping each word to the ids of the documents containing it (in
  document order, each id once per word), and `search(index, term)
  -> list[int]` returning the ids for `term` (empty when absent).
- `searchkit.search` must keep working exactly as before.

The repository's own test suite pins the behaviour and must stay
green.

## What to check

- `build_index` maps every word to the right document ids.
- `search(index, term)` returns the same ids as scanning the
  documents, and needs only the index: it must work even when the
  original documents are gone.

## Boundaries

- Do not change the public API of the `searchkit` package.
- Do not modify the repository test suite under `tests/`.
- Do not add third-party dependencies.
