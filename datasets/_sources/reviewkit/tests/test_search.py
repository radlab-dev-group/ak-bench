"""The finished part of the fixture: the users table exists.

The search itself has no tests yet; that is part of what the review
should notice.
"""

from __future__ import annotations

import sqlite3


def test_the_users_table_round_trips():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO users (name) VALUES ('Ada')")
    rows = conn.execute("SELECT id, name FROM users").fetchall()
    assert rows == [(1, "Ada")]
