"""Immutable public records; event time is an integer, never wall-clock time."""

from dataclasses import dataclass


def integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


@dataclass(frozen=True)
class Event:
    partition: str
    offset: int
    event_id: str
    key: str
    timestamp: int
    value: int

    def __post_init__(self) -> None:
        if not all(
            isinstance(item, str) and item for item in (self.partition, self.event_id, self.key)
        ):
            raise ValueError("partition, event_id and key must be nonempty strings")
        if integer(self.offset, "offset") < 0:
            raise ValueError("offset must be nonnegative")
        integer(self.timestamp, "timestamp")
        integer(self.value, "value")

    @property
    def identity(self) -> tuple[str, int, int]:
        return self.key, self.timestamp, self.value


@dataclass(frozen=True, order=True)
class Result:
    window: str
    key: str
    start: int
    end: int
    count: int
    total: int
    minimum: int
    maximum: int

    @property
    def address(self) -> tuple[str, str, int, int]:
        return self.window, self.key, self.start, self.end


@dataclass(frozen=True)
class Change:
    sequence: int
    operation: str
    result: Result


@dataclass(frozen=True)
class LateEvent:
    event: Event
    watermark: int
