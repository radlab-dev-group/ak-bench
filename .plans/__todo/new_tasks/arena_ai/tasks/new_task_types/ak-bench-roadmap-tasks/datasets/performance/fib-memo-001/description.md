# Memoize the Fibonacci recursion

`fib` in `src/fibkit/naive.py` recomputes every subproblem, so it
takes exponential time. Add a memoized version:

- Create `src/fibkit/memo.py` with `fib(n) -> int` returning the same
  Fibonacci numbers as the naive version (including the `ValueError`
  for negative `n`), but computing each value once.
- `fibkit.fib` must keep working exactly as before.

The repository's own test suite pins the values and must stay green.

## What to check

- `fibkit.memo.fib` returns the same values as the naive `fib` for
  every `n`, and refuses negative `n` the same way.
- Computing a large value (say `fib(30)`) calls the recursive
  function only a handful of times, not millions.

## Boundaries

- Do not change the public API of the `fibkit` package.
- Do not modify the repository test suite under `tests/`.
- Do not add third-party dependencies.
