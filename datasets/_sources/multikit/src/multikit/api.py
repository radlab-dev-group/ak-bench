"""The user API."""

from __future__ import annotations

import sqlite3


def fetch_user(conn: sqlite3.Connection, user_id: int) -> tuple[int, str] | None:
    """The ``(id, name)`` row for ``user_id``, or ``None``."""
    return conn.execute(
        "SELECT id, name FROM users WHERE id = ?", (user_id,)
    ).fetchone()
