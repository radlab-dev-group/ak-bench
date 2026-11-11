"""The finished part of the fixture: single-threaded caching works.

Thread safety and the collector have no tests yet; that is part of what
the review should notice.
"""

from __future__ import annotations

from racekit import get_or_compute


def test_a_value_is_computed_once():
    calls = []

    def factory():
        calls.append(1)
        return 42

    assert get_or_compute("k", factory) == 42
    assert get_or_compute("k", factory) == 42
    assert len(calls) == 1
