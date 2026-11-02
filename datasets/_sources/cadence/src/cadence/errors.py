"""The exceptions the engine raises. Each says what is wrong, not where."""

from __future__ import annotations


class CadenceError(Exception):
    """Base of every error this package raises."""


class UnknownTask(CadenceError, KeyError):
    """A task name the DAG does not hold."""


class UnknownRun(CadenceError, KeyError):
    """A run id the engine does not hold."""


class CycleError(CadenceError):
    """The dependency graph would never reach a fixed point."""

    def __init__(self, cycle: list[str]) -> None:
        super().__init__("dependency cycle: " + " -> ".join(cycle))
        self.cycle = cycle


class LeaseHeld(CadenceError):
    """The resource is held by somebody else and the hold has not expired."""

    def __init__(self, resource: str, holder: str, until: float) -> None:
        super().__init__(f"{resource} is held by {holder!r} until {until:.3f}")
        self.resource = resource
        self.holder = holder
        self.until = until


class LeaseExpired(CadenceError):
    """The lease was already past its deadline when it was offered back."""

    def __init__(self, resource: str, holder: str, epoch: int) -> None:
        super().__init__(f"{resource}: lease of {holder!r} (epoch {epoch}) has expired")
        self.resource = resource
        self.holder = holder
        self.epoch = epoch


class IllegalRunTransition(CadenceError):
    """A run was moved to a state the state machine does not allow."""


class DuplicateRun(CadenceError):
    """The same logical time of a task was materialised twice."""


class CorruptedLog(CadenceError):
    """A record was asked for that the log cannot honour."""
