"""The examples a developer is given: the shape of the contract, not its edges.

They fail on the base commit (the feature is missing) and pass once it is
implemented. They are a subset of the contract, not the whole of it.
"""

from __future__ import annotations

from garden import Plant, plan_watering


def test_a_single_due_plant_is_watered_on_the_first_day():
    plan = plan_watering(
        [Plant("P1", "Fern", 0, 5)], start_day=0, horizon_days=10, capacity_per_day=1
    )
    assert plan == {0: ["P1"]}


def test_earlier_deadlines_are_watered_first():
    plants = [Plant("P1", "Fern", 0, 5), Plant("P2", "Cactus", 0, 3)]
    plan = plan_watering(plants, start_day=0, horizon_days=10, capacity_per_day=1)
    assert plan == {0: ["P2"], 1: ["P1"]}


def test_a_plant_due_after_the_window_is_left_out():
    plan = plan_watering(
        [Plant("P1", "Fern", 0, 20)], start_day=0, horizon_days=10, capacity_per_day=1
    )
    assert plan == {}


def test_capacity_is_hard_when_the_window_is_full():
    plants = [Plant("P1", "Fern", 0, 1), Plant("P2", "Cactus", 0, 1)]
    plan = plan_watering(plants, start_day=5, horizon_days=1, capacity_per_day=1)
    assert plan == {5: ["P1"]}
