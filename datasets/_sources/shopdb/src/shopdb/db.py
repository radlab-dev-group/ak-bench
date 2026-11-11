"""Looking users up by name.

``find_users(conn, name)`` returns ``(id, name)`` rows for the users
whose name is exactly ``name``. The name is data, never SQL: a name
containing quotes or SQL syntax must be looked up literally, and must
never change the shape of the query.
"""

from __future__ import annotations

import sqlite3


def find_users(conn: sqlite3.Connection, name: str) -> list[tuple[int, str]]:
    """Return the ``(id, name)`` rows whose name is exactly ``name``."""
    cursor = conn.execute(f"SELECT id, name FROM users WHERE name = '{name}'")
    return cursor.fetchall()
