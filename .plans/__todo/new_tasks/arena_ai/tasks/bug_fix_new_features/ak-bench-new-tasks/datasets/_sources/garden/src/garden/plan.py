"""Planning watering over a horizon. The rules are in this docstring; the
implementation is the task.

``plan_watering(plants, *, start_day, horizon_days, capacity_per_day)``
returns a dict mapping a day to the plant ids watered that day.

- The window is the days ``start_day`` up to but not including
  ``start_day + horizon_days``. Only plants due inside the window are
  scheduled: a plant whose due day is at or after the end of the window is
  left out entirely.
- A plant's deadline is its due day, except that an overdue plant (due
  before ``start_day``) has deadline ``start_day``: it is as urgent as
  anything due on the first day.
- Plants are considered in ``(deadline, plant_id)`` order. Each plant is
  assigned to the earliest day in the window that still has free capacity
  (``capacity_per_day`` plants per day). A plant is therefore watered as
  early as capacity allows, and the deadline decides who goes first.
- If every day in the window is full when a plant is considered, the plant
  is left out of the plan. Capacity is hard: a day never holds more than
  ``capacity_per_day`` plants.
- Each day's list holds the plant ids in the order they were assigned
  (that is, ``(deadline, plant_id)`` order), and days with no watering are
  omitted from the result.

``horizon_days`` and ``capacity_per_day`` must be positive; anything else
raises :class:`ValueError`. An empty plant list returns an empty dict.
"""

from __future__ import annotations

from collections.abc import Iterable

from garden.model import Plant


def plan_watering(
    plants: Iterable[Plant],
    *,
    start_day: int,
    horizon_days: int,
    capacity_per_day: int,
) -> dict[int, list[str]]:
    """Return the watering plan under the rules in this module."""
    raise NotImplementedError("plan_watering is specified in this module and not yet written")
