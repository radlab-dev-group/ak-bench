# Add a dict-backed user index

`find_user` in `src/indexkit/users.py` scans the whole list on every
lookup. Add an index so repeated lookups are cheap:

- Create `src/indexkit/index.py` with a `UserIndex` class:
  `UserIndex(users)` builds the index once, `find(user_id)` returns
  the matching `User` or `None`, and `len(index)` counts the users.
- `find_user(users, user_id)` must keep working exactly as before.

The repository's own test suite pins the behaviour and must stay
green.

## What to check

- `UserIndex.find` returns the same users as `find_user`, including
  `None` for absent ids.
- `find` does not scan the user list: it answers from a dict built in
  the constructor.

## Boundaries

- Do not change the public API of the `indexkit` package.
- Do not modify the repository test suite under `tests/`.
- Do not add third-party dependencies.
