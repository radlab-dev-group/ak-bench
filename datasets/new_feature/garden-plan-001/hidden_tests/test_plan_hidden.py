"""The specification, tested rule by rule.

Every assertion here is a sentence from the docstring of ``plan_watering``.
"""

from __future__ import annotations

import pytest

from garden import Plant, plan_watering


def test_an_overdue_plant_has_the_first_day_as_its_deadline():
    plants = [
        Plant("P1", "Fern", 0, 5),      # due day 5
        Plant("P2", "Cactus", 0, 2),    # due day 2, overdue at start_day 3
    ]
    plan = plan_watering(plants, start_day=3, horizon_days=10, capacity_per_day=1)
    assert plan == {3: ["P2"], 4: ["P1"]}


def test_a_plant_due_on_the_last_day_of_the_window_is_scheduled():
    plan = plan_watering(
        [Plant("P1", "Fern", 0, 9)], start_day=0, horizon_days=10, capacity_per_day=1
    )
    assert plan == {0: ["P1"]}


def test_a_plant_due_at_the_window_end_is_left_out():
    plan = plan_watering(
        [Plant("P1", "Fern", 0, 10)], start_day=0, horizon_days=10, capacity_per_day=1
    )
    assert plan == {}


def test_equal_deadlines_break_on_plant_id():
    plants = [Plant("P2", "Cactus", 0, 5), Plant("P1", "Fern", 0, 5)]
    plan = plan_watering(plants, start_day=0, horizon_days=10, capacity_per_day=1)
    assert plan == {0: ["P1"], 1: ["P2"]}


def test_several_plants_share_a_day_up_to_capacity():
    plants = [Plant("P1", "Fern", 0, 5), Plant("P2", "Cactus", 0, 3), Plant("P3", "Herb", 0, 4)]
    plan = plan_watering(plants, start_day=0, horizon_days=10, capacity_per_day=2)
    assert plan == {0: ["P2", "P3"], 1: ["P1"]}


def test_a_plant_is_left_out_when_every_day_is_full():
    plants = [Plant("P1", "Fern", 0, 1), Plant("P2", "Cactus", 0, 1), Plant("P3", "Herb", 0, 1)]
    plan = plan_watering(plants, start_day=0, horizon_days=2, capacity_per_day=1)
    assert plan == {0: ["P1"], 1: ["P2"]}


def test_days_without_watering_are_omitted():
    plan = plan_watering(
        [Plant("P1", "Fern", 0, 5)], start_day=0, horizon_days=10, capacity_per_day=3
    )
    assert list(plan) == [0]


def test_an_empty_plant_list_plans_nothing():
    assert plan_watering([], start_day=0, horizon_days=10, capacity_per_day=1) == {}


def test_invalid_arguments_are_refused():
    plants = [Plant("P1", "Fern", 0, 5)]
    with pytest.raises(ValueError):
        plan_watering(plants, start_day=0, horizon_days=0, capacity_per_day=1)
    with pytest.raises(ValueError):
        plan_watering(plants, start_day=0, horizon_days=-1, capacity_per_day=1)
    with pytest.raises(ValueError):
        plan_watering(plants, start_day=0, horizon_days=10, capacity_per_day=0)
