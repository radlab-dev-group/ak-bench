"""The naive recursive Fibonacci."""

from __future__ import annotations


def fib(n: int) -> int:
    """The n-th Fibonacci number, computed by plain recursion."""
    if n < 0:
        raise ValueError("n must not be negative")
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)
