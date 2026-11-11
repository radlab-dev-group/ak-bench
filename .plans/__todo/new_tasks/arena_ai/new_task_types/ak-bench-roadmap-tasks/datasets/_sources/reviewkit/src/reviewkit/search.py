"""Searching users by name fragment."""

from __future__ import annotations

import sqlite3


def find_users(conn: sqlite3.Connection, name: str) -> list[tuple[int, str]]:
    """Users whose name contains ``name``, as ``(id, name)`` rows."""
    query = f"SELECT id, name FROM users WHERE name LIKE '%{name}%'"
    return conn.execute(query).fetchall()
