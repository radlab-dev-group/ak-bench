# searchkit

A tiny document search: `search(docs, term)` scans every document for
every query. It is a benchmark fixture for AK-Bench. The per-query
scan is deliberate: the performance task is to build an inverted
index.

Run the suite with `pytest`.
