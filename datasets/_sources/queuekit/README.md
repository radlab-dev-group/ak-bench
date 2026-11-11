# queuekit

A tiny FIFO queue on a hand-rolled linked list: `Queue` with `enqueue`,
`dequeue` and `__len__`. It is a benchmark fixture for AK-Bench. The
linked list is deliberate: the refactoring task is to reimplement the
backend on `collections.deque` behind the same API.

Run the suite with `pytest`.
