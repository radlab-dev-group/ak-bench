# Reimplement the queue backend on collections.deque

`Queue` in `src/queuekit/queue.py` is hand-rolled on a linked list.
Refactor the backend without changing the behaviour:

- Create `src/queuekit/backend.py` with a `DequeQueue` class backed by
  `collections.deque`, offering `enqueue(value)`, `dequeue()` (front
  value or `None` when empty) and `__len__`.
- `Queue` must delegate to `DequeQueue` and keep its exact behaviour.

The repository's own test suite pins the behaviour and must stay green.

## What to check

- `queuekit.backend.DequeQueue` exists, is backed by `collections.deque`,
  and behaves first-in-first-out.
- `Queue` still behaves exactly as before, including interleaved
  enqueue/dequeue and the empty case.

## Boundaries

- Do not change the public API of the `queuekit` package.
- Do not modify the repository test suite under `tests/`.
- Do not change the queue behaviour.
