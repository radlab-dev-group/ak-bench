"""When a plant needs water.

The rules:

1. A plant is due on ``last_watered_day + interval_days``. The due day
   itself counts: on that day the plant needs water.
2. Rain on a day postpones watering for that day only. A plant that is due
   and it rains needs no water that day, but it needs water on the next
   day that does not rain.
3. Before the due day a plant never needs water, rain or not.
"""

from __future__ import annotations

from collections.abc import Collection

from garden.model import Plant


def due_day(plant: Plant) -> int:
    """The day the plant is next due for water."""
    return plant.last_watered_day + plant.interval_days


def needs_water(plant: Plant, day: int, *, rain_days: Collection[int] = ()) -> bool:
    """True when the plant needs water on ``day``, under the rules above."""
    return day >= due_day(plant) and day not in rain_days


def days_until_due(plant: Plant, day: int) -> int:
    """Whole days from ``day`` until the due day; zero once due or overdue."""
    return max(0, due_day(plant) - day)
