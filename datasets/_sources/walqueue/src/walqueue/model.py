"""Public queue records and explicit integer-time validation."""

from dataclasses import dataclass


def integer(value: object, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def name(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a nonempty string")
    return value


@dataclass(frozen=True)
class Task:
    task_id: str
    payload: dict
    available_at: int
    max_attempts: int
    attempts: int = 0
    generation: int = 0
    status: str = "ready"
    worker: str | None = None
    deadline: int | None = None


@dataclass(frozen=True)
class Lease:
    task_id: str
    worker: str
    generation: int
    deadline: int
    payload: dict
