"""The symptom a developer can reproduce: December plus one is not January."""

from __future__ import annotations

from dates import add_months


def test_december_plus_one_is_january_of_the_next_year():
    assert add_months(2026, 12, 1) == (2027, 1)


def test_moves_inside_a_year_still_work():
    assert add_months(2026, 3, 2) == (2026, 5)
