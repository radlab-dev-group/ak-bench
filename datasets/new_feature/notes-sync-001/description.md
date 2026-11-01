# Implement `merge` from its specification

`merge` in `src/notesapi/sync.py` is declared, documented and tested, but its
body raises `NotImplementedError`. Write it.

The full contract — what counts as a write, how a higher `updated_at` wins, how
tombstones behave, and what the result object must expose — is in the module's
docstring. Read it before writing a line of code; it is the specification, and
the evaluation measures against it.

## The short version

- A note the client has and the server does not is an **insert**.
- A note both have, where the client's `updated_at` is strictly newer, is an
  **update**; when the note is a tombstone, the update is a **delete**.
- A note both have with the same `updated_at`: identical bodies and tags is
  **unchanged**, anything else is a **conflict** — the merge does not guess.
- A note the server has and the client does not is left alone; the client copy
  is not a list of everything that exists.
- The result's `wins` holds the notes the server should now carry, and the five
  lists of ids never overlap.

## Boundaries

- Implement it in `src/notesapi/sync.py`; the public API of `notesapi` stays
  as it is.
- Do not modify the repository test suite under `tests/` and do not add
  third-party dependencies — the standard library is enough.
- The repository's own test suite (`pytest`) has to stay green, so the
  `store`, `errors` and `search` modules and their behaviour must keep working.
