"""The defect, proven from every side the mutation can hide behind.

The hidden tests pass on the base commit and fail once the mutation is
applied; that is the contract of a bug-fix task (docs/DATASETS.md). They
cover the due day from both sides, the rain interaction, and the two
functions that must not change meaning.
"""

from __future__ import annotations

from garden import Plant, days_until_due, due_day, needs_water


def test_the_due_day_is_inclusive():
    plant = Plant("P1", "Fern", 10, 5)
    assert due_day(plant) == 15
    assert needs_water(plant, 15)
    assert needs_water(plant, 16)


def test_the_day_before_the_due_day_is_not_due():
    plant = Plant("P1", "Fern", 10, 5)
    assert not needs_water(plant, 14)
    assert not needs_water(plant, 10)


def test_a_one_day_interval_is_due_the_next_day():
    plant = Plant("P1", "Cactus", 7, 1)
    assert needs_water(plant, 8)
    assert not needs_water(plant, 7)


def test_rain_on_the_due_day_postpones_by_one_day():
    plant = Plant("P1", "Fern", 10, 5)
    assert not needs_water(plant, 15, rain_days={15})
    assert needs_water(plant, 16, rain_days={15})


def test_rain_before_the_due_day_changes_nothing():
    plant = Plant("P1", "Fern", 10, 5)
    assert not needs_water(plant, 14, rain_days={14})
    assert needs_water(plant, 15, rain_days={14})


def test_consecutive_rain_days_postpone_until_a_dry_day():
    plant = Plant("P1", "Fern", 10, 5)
    rain = {15, 16, 17}
    assert not needs_water(plant, 17, rain_days=rain)
    assert needs_water(plant, 18, rain_days=rain)


def test_days_until_due_reaches_zero_on_the_due_day():
    plant = Plant("P1", "Fern", 10, 5)
    assert days_until_due(plant, 14) == 1
    assert days_until_due(plant, 15) == 0
    assert days_until_due(plant, 16) == 0
