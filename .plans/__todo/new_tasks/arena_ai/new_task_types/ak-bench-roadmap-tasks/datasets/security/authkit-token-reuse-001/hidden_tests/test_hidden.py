"""The vulnerabilities, proven from every side.

These tests fail on the base commit (the vulnerabilities are in the base
code) and pass once both are closed.
"""

from __future__ import annotations

from authkit import SessionStore


def test_a_logged_out_session_is_refused_immediately():
    store = SessionStore(ttl=100)
    token = store.create_session("Ada", now=0)
    store.logout(token)
    assert store.validate(token, now=1) is None


def test_a_session_is_refused_at_its_expiry_instant():
    store = SessionStore(ttl=100)
    token = store.create_session("Ada", now=0)
    assert store.validate(token, now=99) == "Ada"
    assert store.validate(token, now=100) is None


def test_a_session_is_refused_long_after_expiry():
    store = SessionStore(ttl=100)
    token = store.create_session("Ada", now=0)
    assert store.validate(token, now=10_000) is None


def test_logout_does_not_affect_other_sessions():
    store = SessionStore(ttl=100)
    ada = store.create_session("Ada", now=0)
    bob = store.create_session("Bob", now=0)
    store.logout(ada)
    assert store.validate(ada, now=10) is None
    assert store.validate(bob, now=10) == "Bob"


def test_logging_out_an_unknown_token_is_harmless():
    store = SessionStore(ttl=100)
    store.logout("nope")
    token = store.create_session("Ada", now=0)
    assert store.validate(token, now=10) == "Ada"


def test_a_new_session_for_the_same_user_still_validates():
    store = SessionStore(ttl=100)
    old = store.create_session("Ada", now=0)
    store.logout(old)
    fresh = store.create_session("Ada", now=10)
    assert store.validate(fresh, now=20) == "Ada"
    assert store.validate(old, now=20) is None
