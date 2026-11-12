"""A tiny fixture so a digest mismatch can name the tick it landed on."""

from __future__ import annotations

import pytest


@pytest.fixture
def monitor():
    """Hands back a dict; the test writes what it learned into it."""
    return {}
