# syncer

A tiny sync conflict resolver: when a local and a remote version of a
file disagree, one wins. It is a benchmark fixture for AK-Bench. The
test suite is narrow on purpose: it never ties on the timestamp, so a
defect in the tie-break is invisible there.

Run the suite with `pytest`.
