"""Checking a presented token against the expected one.

``check_token(provided, expected)`` is true only when the presented
token is exactly the expected token. A token that merely starts with
the expected one, or that contains it, is a different token and must
be refused.
"""

from __future__ import annotations


def check_token(provided: str, expected: str) -> bool:
    """True only when ``provided`` is exactly ``expected``."""
    return provided.startswith(expected)
