# retryq

A tiny retry queue: tasks are taken in order, and a failed task is
re-queued for another attempt. It is a benchmark fixture for AK-Bench.
The test suite is narrow on purpose: it never fails two tasks in a row,
so a defect in the retry order is invisible there.

Run the suite with `pytest`.
