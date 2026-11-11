"""The refactoring, proven: target structure plus preserved behaviour.

These tests fail on the base commit (the target module does not exist)
and pass once the decision is flattened.
"""

from __future__ import annotations

from rules import decide
from rules.predicates import is_adult, is_member


def test_is_adult_boundary():
    assert is_adult(18)
    assert is_adult(99)
    assert not is_adult(17)
    assert not is_adult(0)


def test_is_member_echoes_the_fact():
    assert is_member(True)
    assert not is_member(False)


def test_the_full_decision_table_is_unchanged():
    assert decide(30, False, True) == "vip"
    assert decide(30, True, True) == "vip"
    assert decide(30, True, False) == "standard"
    assert decide(30, False, False) == "deny"
    assert decide(15, True, True) == "standard"
    assert decide(15, True, False) == "deny"
    assert decide(15, False, True) == "deny"
    assert decide(15, False, False) == "deny"
    assert decide(18, True, False) == "standard"
    assert decide(17, True, True) == "standard"
