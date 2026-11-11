"""The command line front end."""

from __future__ import annotations

import sqlite3

from multikit.api import get_user


def show_user(conn: sqlite3.Connection, user_id: int) -> str:
    """One line describing the user."""
    user = get_user(conn, user_id)
    return f"{user[0]}: {user[1]}"
