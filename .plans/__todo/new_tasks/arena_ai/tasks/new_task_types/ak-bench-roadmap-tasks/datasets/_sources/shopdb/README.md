# shopdb

A tiny user lookup over sqlite3: `find_users(conn, name)` returns the
users whose name matches. It is a benchmark fixture for AK-Bench. The
test suite is narrow on purpose: it only looks up plain names, so an
injection defect is invisible there.

Run the suite with `pytest`.
