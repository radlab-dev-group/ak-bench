"""The vulnerability, proven from every side.

These tests fail on the base commit (the vulnerability is in the base
code) and pass once the injection is closed.
"""

from __future__ import annotations

import sqlite3

from shopdb import find_users


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.executemany(
        "INSERT INTO users (id, name) VALUES (?, ?)",
        [(1, "Ada"), (2, "Bob"), (3, "O'Brien")],
    )
    return conn


def test_an_injection_probe_returns_nothing():
    assert find_users(make_db(), "' OR '1'='1") == []


def test_a_comment_probe_returns_nothing():
    assert find_users(make_db(), "Ada' --") == []


def test_a_union_probe_returns_nothing():
    assert find_users(make_db(), "' UNION SELECT id, name FROM users --") == []


def test_a_name_with_a_quote_finds_its_user():
    assert find_users(make_db(), "O'Brien") == [(3, "O'Brien")]


def test_the_table_survives_a_destructive_probe():
    conn = make_db()
    assert find_users(conn, "'; DROP TABLE users; --") == []
    assert find_users(conn, "Ada") == [(1, "Ada")]


def test_plain_lookups_still_work():
    conn = make_db()
    assert find_users(conn, "Bob") == [(2, "Bob")]
    assert find_users(conn, "Nobody") == []
