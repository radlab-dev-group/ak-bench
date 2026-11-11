# Make the deduplication linear

`unique` in `src/dedupkit/dedup.py` checks every item against every
already-kept item, so it costs quadratic time. Rewrite it to run in
linear time while keeping the exact behaviour: duplicates removed,
first occurrences kept, order preserved.

The repository's own test suite pins the behaviour and must stay
green.

## What to check

- `unique` returns the same lists as before for every input.
- The implementation does not compare each item against all kept
  items (a set-based membership test is the natural fit).

## Boundaries

- Do not change the public API of the `dedupkit` package.
- Do not modify the repository test suite under `tests/`.
- Do not add third-party dependencies.
