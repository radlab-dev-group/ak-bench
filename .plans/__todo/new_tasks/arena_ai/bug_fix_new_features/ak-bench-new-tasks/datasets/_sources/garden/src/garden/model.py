"""The plant record. Days are plain integers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Plant:
    """One plant: when it was last watered and how often it needs water.

    ``last_watered_day`` is the day number of the last watering and
    ``interval_days`` is how many days later it is due again, so the due
    day is ``last_watered_day + interval_days``.
    """

    plant_id: str
    name: str
    last_watered_day: int
    interval_days: int

    def __post_init__(self) -> None:
        if not self.plant_id:
            raise ValueError("a plant needs an id")
        if self.interval_days < 1:
            raise ValueError(
                f"interval_days must be at least 1, got {self.interval_days}"
            )
