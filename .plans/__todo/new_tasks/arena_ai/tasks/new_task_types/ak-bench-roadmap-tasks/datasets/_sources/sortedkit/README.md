# sortedkit

A tiny sorted-list search: `find_position(items, target)` scans a
sorted list linearly. It is a benchmark fixture for AK-Bench. The
linear scan is deliberate: the performance task is to add a binary
search.

Run the suite with `pytest`.
