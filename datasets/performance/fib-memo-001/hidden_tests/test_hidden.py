"""The memoization, proven: same values, a handful of calls.

The hidden tests count ``fib`` calls with ``sys.setprofile``: the
naive recursion needs millions of calls for ``fib(30)``, the memoized
one dozens.
"""

from __future__ import annotations

import sys

import pytest

from fibkit import fib as naive_fib
from fibkit.memo import fib


def test_memoized_fib_matches_the_naive_values():
    assert fib(0) == 0
    assert fib(1) == 1
    assert fib(2) == 1
    assert fib(10) == 55
    assert fib(20) == naive_fib(20)
    assert fib(25) == 75025


def test_negative_is_refused():
    with pytest.raises(ValueError):
        fib(-1)


def test_memoized_fib_calls_itself_few_times():
    calls = 0

    def tracer(frame, event, arg):
        nonlocal calls
        if event == "call" and frame.f_code.co_name == "fib":
            calls += 1
        return tracer

    sys.setprofile(tracer)
    try:
        result = fib(30)
    finally:
        sys.setprofile(None)
    assert result == 832040
    assert calls < 500, f"{calls} calls: the recursion is not memoized"
