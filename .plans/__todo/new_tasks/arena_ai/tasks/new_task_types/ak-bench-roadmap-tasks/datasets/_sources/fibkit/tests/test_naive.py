"""The finished part of the fixture: Fibonacci values.

These tests pin the values the memoized version must reproduce.
"""

from __future__ import annotations

import pytest

from fibkit import fib


def test_small_values():
    assert fib(0) == 0
    assert fib(1) == 1
    assert fib(10) == 55


def test_negative_is_refused():
    with pytest.raises(ValueError):
        fib(-1)
