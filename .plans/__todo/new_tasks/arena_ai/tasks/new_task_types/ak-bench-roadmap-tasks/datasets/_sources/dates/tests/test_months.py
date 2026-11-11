"""The finished part of the fixture: moves inside one year.

The suite deliberately never crosses a year boundary, so a defect there
is invisible here.
"""

from __future__ import annotations

import pytest

from dates import add_months


def test_adding_months_inside_a_year():
    assert add_months(2026, 3, 2) == (2026, 5)
    assert add_months(2026, 6, 3) == (2026, 9)


def test_subtracting_months_inside_a_year():
    assert add_months(2026, 6, -2) == (2026, 4)


def test_zero_months_changes_nothing():
    assert add_months(2026, 7, 0) == (2026, 7)


def test_an_invalid_month_is_refused():
    with pytest.raises(ValueError):
        add_months(2026, 0, 1)
    with pytest.raises(ValueError):
        add_months(2026, 13, 1)
