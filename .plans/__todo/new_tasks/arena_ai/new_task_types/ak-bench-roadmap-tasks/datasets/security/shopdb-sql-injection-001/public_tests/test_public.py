"""The symptom a developer can reproduce: ' OR '1'='1 returns everyone."""

from __future__ import annotations

import sqlite3

from shopdb import find_users


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.executemany(
        "INSERT INTO users (id, name) VALUES (?, ?)", [(1, "Ada"), (2, "Bob")]
    )
    return conn


def test_an_injection_probe_returns_nothing():
    assert find_users(make_db(), "' OR '1'='1") == []


def test_a_plain_lookup_still_works():
    assert find_users(make_db(), "Ada") == [(1, "Ada")]
