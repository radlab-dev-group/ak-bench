"""The finished part of the fixture: plain lookups.

The suite deliberately never looks up a name with quotes or SQL syntax,
so an injection defect is invisible here.
"""

from __future__ import annotations

import sqlite3

from shopdb import find_users


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.executemany(
        "INSERT INTO users (id, name) VALUES (?, ?)",
        [(1, "Ada"), (2, "Bob"), (3, "Cy")],
    )
    return conn


def test_finds_a_user_by_name():
    assert find_users(make_db(), "Ada") == [(1, "Ada")]


def test_an_unknown_name_finds_nothing():
    assert find_users(make_db(), "Nobody") == []
