"""The symptom a developer can reproduce: a prefixed token is accepted."""

from __future__ import annotations

from authkit import check_token


def test_a_prefixed_token_is_refused():
    assert not check_token("secret-token-extra", "secret-token")


def test_the_exact_token_is_accepted():
    assert check_token("secret-token", "secret-token")
