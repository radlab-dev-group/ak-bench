# authkit

A tiny auth helper: token checking and sessions on logical time (the
caller supplies `now`). It is a benchmark fixture for AK-Bench. The test
suite is narrow on purpose: it only checks exact tokens and fresh
sessions, so prefix-match and reuse defects are invisible there.

Run the suite with `pytest`.
