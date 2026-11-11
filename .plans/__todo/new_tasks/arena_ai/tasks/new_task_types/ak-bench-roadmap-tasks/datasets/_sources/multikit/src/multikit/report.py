"""Usage reporting."""

from __future__ import annotations

import sqlite3


def usage_report(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """``(name, order_count)`` for every user."""
    rows = conn.execute("SELECT id, name FROM users").fetchall()
    report = []
    for user_id, name in rows:
        count = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        report.append((name, count))
    return report
