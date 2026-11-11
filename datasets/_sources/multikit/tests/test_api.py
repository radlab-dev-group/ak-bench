"""The finished part of the fixture: fetching a user works.

The CLI and the report have no tests yet; that is part of what the
review should notice.
"""

from __future__ import annotations

import sqlite3

from multikit import fetch_user


def test_fetch_user_returns_the_row():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO users (name) VALUES ('Ada')")
    assert fetch_user(conn, 1) == (1, "Ada")
    assert fetch_user(conn, 99) is None
