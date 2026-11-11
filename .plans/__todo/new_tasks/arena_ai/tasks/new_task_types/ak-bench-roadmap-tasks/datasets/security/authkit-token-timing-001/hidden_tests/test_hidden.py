"""The vulnerability, proven from every side.

These tests fail on the base commit (the vulnerability is in the base
code) and pass once the check is exact and constant-time.
"""

from __future__ import annotations

import hmac

from authkit import check_token
from authkit import tokens


def test_the_exact_token_is_accepted():
    assert check_token("secret-token", "secret-token")


def test_a_prefixed_token_is_refused():
    assert not check_token("secret-token-extra", "secret-token")


def test_a_token_containing_the_expected_one_is_refused():
    assert not check_token("xxsecret-token", "secret-token")


def test_an_empty_token_is_refused():
    assert not check_token("", "secret-token")


def test_a_case_difference_is_refused():
    assert not check_token("Secret-Token", "secret-token")


def test_the_comparison_is_constant_time(monkeypatch):
    calls = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    monkeypatch.setattr(tokens.hmac, "compare_digest", spy, raising=False)
    assert check_token("secret-token", "secret-token")
    assert calls, "check_token must compare with hmac.compare_digest"
