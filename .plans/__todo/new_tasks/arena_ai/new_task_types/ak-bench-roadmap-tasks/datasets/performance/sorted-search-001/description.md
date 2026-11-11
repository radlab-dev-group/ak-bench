# Add a binary search for the sorted list

`find_position` in `src/sortedkit/scan.py` scans linearly even though
the list is sorted. Add a binary search:

- Create `src/sortedkit/search.py` with `find_position(items, target)
  -> int`: the index of `target` in the sorted `items`, or -1 when
  absent. With duplicates, any index holding the target is fine.
- `sortedkit.find_position` must keep working with the same signature
  and results, delegating to the binary search.

The repository's own test suite pins the behaviour and must stay
green.

## What to check

- `sortedkit.search.find_position` returns a correct index (or -1)
  for present and absent targets, including empty lists and the ends.
- The search is logarithmic: it does not walk the list one by one.

## Boundaries

- Do not change the public API of the `sortedkit` package.
- Do not modify the repository test suite under `tests/`.
- Do not add third-party dependencies.
