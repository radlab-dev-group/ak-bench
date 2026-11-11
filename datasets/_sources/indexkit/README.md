# indexkit

A tiny user lookup: `find_user(users, user_id)` scans a list of users.
It is a benchmark fixture for AK-Bench. The linear scan is deliberate:
the performance task is to add a dict-backed index.

Run the suite with `pytest`.
