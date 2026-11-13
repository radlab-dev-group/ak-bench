"""The memoization, proven: same values, a handful of calls, and it converges.

The hidden tests count ``fib`` calls with ``sys.setprofile``: the naive recursion
needs millions of calls for ``fib(30)``, the memoized one dozens.

Counting calls alone is not enough. A table of precomputed values answers every
small ``n`` with no recursion at all, and passed this task until one test asked
for a value no small table holds: ``fib(400)``, in a subprocess with a deadline,
which a table cannot answer and an exponential recursion cannot survive.
"""

from __future__ import annotations

import subprocess
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


#: How long a memoized ``fib(400)`` is allowed to take. An implementation that
#: computes each value once needs milliseconds; a precomputed table fails
#: outright, and the naive recursion needs longer than the age of the universe.
#: Measuring in a subprocess turns that last case into a bounded failure instead
#: of an evaluation that never returns.
LARGE_N_DEADLINE_SECONDS = 20


def test_the_function_computes_a_value_beyond_any_small_table():
    """``fib`` has to be an algorithm, not a table of the values a test asked for."""
    expected = _fib_by_iteration(400)
    script = (
        "import sys\n"
        "from fibkit.memo import fib\n"
        "sys.stdout.write(str(fib(400)))\n"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=LARGE_N_DEADLINE_SECONDS,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"fib(400) did not finish in {LARGE_N_DEADLINE_SECONDS}s: either the "
            "recursion is still exponential, or the answer comes from a table"
        )
    assert completed.returncode == 0, (
        f"fib(400) failed: {completed.stderr.strip()[-400:]}"
    )
    assert completed.stdout.strip() == str(expected), (
        "fib(400) is not the 400th Fibonacci number"
    )


def _fib_by_iteration(n: int) -> int:
    """The value the subprocess has to produce, computed without the module."""
    previous, current = 0, 1
    for _ in range(n):
        previous, current = current, previous + current
    return previous
