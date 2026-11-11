"""The failing scenario, proven from every side.

These tests fail on the base commit (the defect is in the base code) and
pass once the arithmetic is repaired.
"""

from __future__ import annotations

import pytest

from dates import add_months


def test_december_plus_one_is_january_of_the_next_year():
    assert add_months(2026, 12, 1) == (2027, 1)


def test_january_minus_one_is_december_of_the_previous_year():
    assert add_months(2026, 1, -1) == (2025, 12)


def test_twelve_months_lands_on_the_same_month():
    assert add_months(2026, 6, 12) == (2027, 6)
    assert add_months(2026, 6, -12) == (2025, 6)


def test_a_move_landing_on_january_from_any_month():
    assert add_months(2026, 11, 2) == (2027, 1)
    assert add_months(2026, 2, -1) == (2026, 1)


def test_a_move_landing_on_december():
    assert add_months(2026, 1, 11) == (2026, 12)
    assert add_months(2027, 1, -1) == (2026, 12)


def test_several_years_forward_and_back():
    assert add_months(2026, 12, 25) == (2029, 1)
    assert add_months(2026, 1, -25) == (2023, 12)


def test_moves_inside_a_year_still_work():
    assert add_months(2026, 3, 2) == (2026, 5)
    assert add_months(2026, 6, -2) == (2026, 4)


def test_an_invalid_month_is_still_refused():
    with pytest.raises(ValueError):
        add_months(2026, 0, 1)
    with pytest.raises(ValueError):
        add_months(2026, 13, 1)
