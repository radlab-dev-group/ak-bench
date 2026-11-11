"""The finished part of the fixture: search behaviour.

These tests pin the behaviour the binary search must preserve.
"""

from __future__ import annotations

from sortedkit import find_position


def test_finds_a_present_target():
    assert find_position([1, 3, 5, 7], 5) == 2


def test_returns_minus_one_when_absent():
    assert find_position([1, 3, 5, 7], 4) == -1
    assert find_position([], 4) == -1
