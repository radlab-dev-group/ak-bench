"""The finished part of the fixture: exact tokens and fresh sessions.

The suite deliberately never presents a token with extra characters and
never validates after logout or expiry, so those defects are invisible
here.
"""

from __future__ import annotations

from authkit import SessionStore, check_token


def test_an_exact_token_is_accepted_and_a_wrong_one_refused():
    assert check_token("secret-token", "secret-token")
    assert not check_token("wrong-token", "secret-token")


def test_a_fresh_session_validates():
    store = SessionStore(ttl=100)
    token = store.create_session("Ada", now=0)
    assert store.validate(token, now=50) == "Ada"
    assert store.validate("nope", now=50) is None
