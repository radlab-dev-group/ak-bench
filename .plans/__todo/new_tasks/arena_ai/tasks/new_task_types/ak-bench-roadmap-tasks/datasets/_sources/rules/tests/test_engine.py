"""The finished part of the fixture: the decision table.

These tests pin the behaviour the refactoring must preserve.
"""

from __future__ import annotations

from rules import decide


def test_an_adult_member_is_vip():
    assert decide(30, False, True) == "vip"


def test_an_adult_with_a_ticket_is_standard():
    assert decide(30, True, False) == "standard"


def test_a_minor_with_ticket_and_membership_is_standard():
    assert decide(15, True, True) == "standard"


def test_everyone_else_is_denied():
    assert decide(30, False, False) == "deny"
    assert decide(15, True, False) == "deny"
    assert decide(15, False, True) == "deny"
