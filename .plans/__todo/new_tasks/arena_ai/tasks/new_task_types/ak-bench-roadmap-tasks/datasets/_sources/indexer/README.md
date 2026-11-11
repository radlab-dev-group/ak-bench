# indexer

A tiny full-text indexer: documents are added, deleted, and searched by
term. It is a benchmark fixture for AK-Bench. The test suite is narrow on
purpose: it never searches for a term after deleting the only document
that contained it, so a stale-index defect is invisible there.

Run the suite with `pytest`.
