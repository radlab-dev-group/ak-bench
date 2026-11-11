"""What a developer is told about this defect: the due day is inclusive.

These tests are visible to the agent. They state the rule and probe it at
the edges the hidden tests also care about, so an agent can find the defect
without being handed the exact assertions the evaluation uses.
"""

from __future__ import annotations

from garden import Plant, days_until_due, needs_water


def test_a_plant_needs_water_on_its_due_day():
    plant = Plant("P1", "Fern", 10, 5)  # due on day 15
    assert needs_water(plant, 15)


def test_a_plant_needs_no_water_the_day_before():
    plant = Plant("P1", "Fern", 10, 5)
    assert not needs_water(plant, 14)


def test_rain_on_the_due_day_postpones_to_the_next_day():
    plant = Plant("P1", "Fern", 10, 5)
    assert not needs_water(plant, 15, rain_days={15})
    assert needs_water(plant, 16, rain_days={15})


def test_no_days_are_left_on_the_due_day():
    plant = Plant("P1", "Fern", 10, 5)
    assert days_until_due(plant, 15) == 0
