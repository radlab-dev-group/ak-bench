# Back-to-back lessons are reported as overlapping

The timetable in `src/timetable` stores lessons as half-open intervals
`[start, end)` in minutes from midnight, and the rules are documented in
`src/timetable/overlap.py`. Read them before touching anything.

A lesson that ends at minute 600 and another that starts at minute 600 are
back-to-back: the first occupies minutes up to but not including 600, and
the second starts at 600. They do not overlap, and a slot that starts the
minute a lesson ends is free.

Today, back-to-back lessons are reported as overlapping. Find out where,
and fix it so the package matches its documentation.

## What to check

- `overlaps` in `src/timetable/overlap.py` for intervals that touch at an
  endpoint, in both directions.
- `conflicts` must not list a back-to-back pair, and must still list a pair
  that shares even one minute.
- `is_free` must accept a slot that starts exactly when a lesson ends.

## Boundaries

- Do not change the public API of the `timetable` package.
- Do not modify the repository test suite under `tests/`.
- The repository's own test suite has to stay green after your change.
