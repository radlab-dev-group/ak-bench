"""The symptoms a developer can reproduce: logout and expiry are ignored."""

from __future__ import annotations

from authkit import SessionStore


def test_a_logged_out_session_is_refused():
    store = SessionStore(ttl=100)
    token = store.create_session("Ada", now=0)
    store.logout(token)
    assert store.validate(token, now=10) is None


def test_an_expired_session_is_refused():
    store = SessionStore(ttl=100)
    token = store.create_session("Ada", now=0)
    assert store.validate(token, now=100) is None


def test_a_fresh_session_still_validates():
    store = SessionStore(ttl=100)
    token = store.create_session("Ada", now=0)
    assert store.validate(token, now=50) == "Ada"
