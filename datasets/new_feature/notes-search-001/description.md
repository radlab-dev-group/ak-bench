# Implement `search_notes` from its specification

`search_notes` in `src/notesapi/search.py` is declared, documented and tested,
but its body raises `NotImplementedError`. Write it.

The full contract — matching, ranking, filtering and paging, in the order the
rules are applied — is in the module's docstring. Read it before writing a line
of code; it is the specification, and the evaluation measures against it.

## The short version

- A query is whitespace-separated terms; a note matches when **every** term
  occurs (case-insensitively, as a substring) in its body or a tag.
- An empty or blank query matches every live note.
- Score: one point per term found in the body, two per term found in a tag.
- Order: score descending, then `updated_at` descending, then `note_id`
  ascending.
- Deleted notes never match. With `tags`, a note must carry every one of them
  (case-insensitively) to be considered. `offset` skips, `limit` caps
  (`None` = no cap); a negative `offset` or `limit` raises `ValueError`.
- Return the notes, not their ids. Never modify the store.

## Boundaries

- Implement it in `src/notesapi/search.py`; the public API of `notesapi` stays
  as it is.
- Do not modify the repository test suite under `tests/` and do not add
  third-party dependencies — the standard library is enough.
- The repository's own test suite (`pytest`) has to stay green, so the
  `store`, `errors`, `sync` modules and their behaviour must keep working.
