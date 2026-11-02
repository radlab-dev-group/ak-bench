"""Mergeable exact integer aggregates used by every window kind."""

from dataclasses import dataclass

from .model import Result


@dataclass
class Accumulator:
    count: int = 0
    total: int = 0
    minimum: int | None = None
    maximum: int | None = None

    def add(self, value: int) -> None:
        self.count += 1
        self.total += value
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)

    def merge(self, other: "Accumulator") -> None:
        if not other.count:
            return
        self.count += other.count
        self.total += other.total
        self.minimum = other.minimum if self.minimum is None else min(self.minimum, other.minimum)
        self.maximum = other.maximum if self.maximum is None else max(self.maximum, other.maximum)

    def result(self, window: str, key: str, start: int, end: int) -> Result:
        if not self.count:
            raise ValueError("an empty accumulator has no result")
        return Result(window, key, start, end, self.count, self.total, self.minimum, self.maximum)
