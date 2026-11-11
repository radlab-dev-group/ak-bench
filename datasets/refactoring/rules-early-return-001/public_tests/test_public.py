"""The target structure, in miniature: predicates exist and decisions hold."""

from __future__ import annotations

from rules import decide
from rules.predicates import is_adult, is_member


def test_the_predicates_answer_the_facts():
    assert is_adult(18)
    assert not is_adult(17)
    assert is_member(True)
    assert not is_member(False)


def test_decide_still_works():
    assert decide(30, False, True) == "vip"
    assert decide(30, False, False) == "deny"
