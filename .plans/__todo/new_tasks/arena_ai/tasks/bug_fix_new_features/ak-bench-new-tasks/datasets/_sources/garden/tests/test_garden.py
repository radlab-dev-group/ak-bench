"""The finished part of the fixture: the plant record and due-day maths.

The suite deliberately never asks about the due day itself, so a defect at
that boundary is invisible here.
"""

from __future__ import annotations

import pytest

from garden import Plant, days_until_due, due_day, needs_water


def test_a_plant_needs_an_id_and_a_positive_interval():
    with pytest.raises(ValueError):
        Plant("", "Fern", 0, 3)
    with pytest.raises(ValueError):
        Plant("P1", "Fern", 0, 0)


def test_the_due_day_is_last_watered_plus_interval():
    assert due_day(Plant("P1", "Fern", 10, 3)) == 13


def test_a_plant_well_before_its_due_day_needs_no_water():
    plant = Plant("P1", "Fern", 10, 5)
    assert not needs_water(plant, 11)
    assert not needs_water(plant, 12)


def test_an_overdue_plant_needs_water():
    plant = Plant("P1", "Fern", 10, 5)
    assert needs_water(plant, 20)
    assert needs_water(plant, 100)


def test_rain_on_an_overdue_day_postpones_watering_for_that_day():
    plant = Plant("P1", "Fern", 10, 5)
    assert not needs_water(plant, 20, rain_days={20})
    assert needs_water(plant, 21, rain_days={20})


def test_days_until_due_counts_down_and_stops_at_zero():
    plant = Plant("P1", "Fern", 10, 5)
    assert days_until_due(plant, 10) == 5
    assert days_until_due(plant, 13) == 2
    assert days_until_due(plant, 20) == 0
