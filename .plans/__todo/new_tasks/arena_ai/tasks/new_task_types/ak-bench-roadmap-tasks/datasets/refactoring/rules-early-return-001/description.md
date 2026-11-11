# Flatten the nested entry decision with early returns and predicates

`decide` in `src/rules/engine.py` is written as deeply nested branches.
Refactor it without changing any decision:

- Create `src/rules/predicates.py` with `is_adult(age) -> bool` (true
  from 18) and `is_member(is_member) -> bool` (the membership fact,
  named so the decision reads as a sentence). Both take the raw fact
  and return a plain bool.
- Rewrite `decide` with early returns, using those predicates, so the
  decision reads top-down instead of nesting.

The repository's own test suite pins the decision table and must stay
green.

## What to check

- `rules.predicates.is_adult` and `is_member` exist with the
  signatures above.
- `decide` returns the same level for every combination of age,
  ticket and membership.

## Boundaries

- Do not change the public API of the `rules` package.
- Do not modify the repository test suite under `tests/`.
- Do not change the decision rules themselves.
