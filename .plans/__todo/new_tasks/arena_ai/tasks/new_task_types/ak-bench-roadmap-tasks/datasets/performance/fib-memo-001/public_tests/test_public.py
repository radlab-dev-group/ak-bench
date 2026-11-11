"""The memoization, in miniature: same values, few calls."""

from __future__ import annotations

import sys

from fibkit import fib as naive_fib
from fibkit.memo import fib


def test_memoized_fib_matches_the_naive_values():
    assert fib(0) == 0
    assert fib(1) == 1
    assert fib(10) == 55
    assert fib(20) == naive_fib(20)


def test_memoized_fib_calls_itself_few_times():
    calls = 0

    def tracer(frame, event, arg):
        nonlocal calls
        if event == "call" and frame.f_code.co_name == "fib":
            calls += 1
        return tracer

    sys.setprofile(tracer)
    try:
        result = fib(25)
    finally:
        sys.setprofile(None)
    assert result == 75025
    assert calls < 500
