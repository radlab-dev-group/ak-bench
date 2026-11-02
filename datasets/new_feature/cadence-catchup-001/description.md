# Implement `plan_catch_up` from its specification

`plan_catch_up` in `src/cadence/catchup.py` is declared, documented and tested,
but its body raises `NotImplementedError`. Write it.

The full contract — what a window contains, when an occurrence is already taken
care of, when it cannot be planned yet, how a skip propagates, what the cap
means, and in which order the plan has to come back — is in the module's
docstring. Read it before writing a line of code; it is the specification, and
the evaluation measures against it.

## The short version

- The window is `[start, end)`, like every other window in this package. An
  occurrence the time zone skipped does not exist.
- A run in `history` at that exact logical time settles the occurrence when it
  succeeded or is still in flight; a `failed` run does not — the operator asked
  for the window and did not get it.
- A dependency that cannot be satisfied is a **skip with a reason**, not a
  silent omission, and a skip blocks what waits on it.
- The plan comes back in an order the scheduler could execute top-down: oldest
  first, and a waiting task never before the task it waits for.

## Boundaries

- Implement it in `src/cadence/catchup.py`; the public API of `cadence` stays as
  it is, and nothing else in the package changes.
- The planner is pure: no clock, no log, no mutation of the DAG or the history.
  Calling it twice on the same input returns the same plan.
- Do not add third-party dependencies — the standard library is enough.
- The repository's own test suite (`pytest`) has to stay green.
