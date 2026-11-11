# dedupkit

A tiny deduplication helper: `unique(items)` removes duplicates while
keeping the first occurrence of each item. It is a benchmark fixture
for AK-Bench. The implementation is quadratic on purpose: the
performance task is to make it linear.

Run the suite with `pytest`.
