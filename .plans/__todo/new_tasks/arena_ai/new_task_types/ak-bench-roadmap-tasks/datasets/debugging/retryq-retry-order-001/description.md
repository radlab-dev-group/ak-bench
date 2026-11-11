# A failed task jumps the queue instead of going to the back

`RetryQueue` in `src/retryq/queue.py` is documented to take tasks first
in, first out, and to re-queue a failed task **at the back**, behind
everything already waiting.

Today, when two tasks fail in a row, the second failed task is taken
before the tasks that were already waiting: a failing task can starve
the queue. The repository's own test suite never fails two tasks in a
row, so it stays green.

Diagnose the failing scenario and repair the retry order so a failed
task always goes behind everything already waiting.

## What to check

- Two failures in a row: the waiting tasks come before the retries.
- A failure interleaved with new enqueues.
- Plain first-in-first-out order and the unknown-task refusal must keep
  working.

## Boundaries

- Do not change the public API of the `retryq` package.
- Do not modify the repository test suite under `tests/`.
- The repository's own test suite has to stay green after your change.
