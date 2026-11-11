# A deleted document is still found by search

`Indexer` in `src/indexer/index.py` is documented to remove a deleted
document from the index entirely: a deleted document must never be
found again, unless it is added again.

Today, after a document is deleted, search still returns it when it was
the only document containing the term. The repository's own test suite
never searches after deleting the only document with a term, so it
stays green.

Diagnose the failing scenario and repair the index so deleted documents
are never found again.

## What to check

- Delete the only document with a term, then search for that term.
- Delete one of two documents with a term: the other must still be found.
- Re-adding a deleted document must make it searchable again, and
  replacing a document must keep working.

## Boundaries

- Do not change the public API of the `indexer` package.
- Do not modify the repository test suite under `tests/`.
- The repository's own test suite has to stay green after your change.
