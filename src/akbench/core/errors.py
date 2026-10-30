"""Exception hierarchy for AK-Bench.

Infrastructure problems must stay distinguishable from agent or evaluation
failures (implementation plan, rule 11), so the base error carries a
``failure_class`` label that higher layers can record without guessing.
"""

from __future__ import annotations

from enum import StrEnum


class FailureClass(StrEnum):
    """Origin of a failure, used in reports and stored run records."""

    CONFIGURATION = "configuration"
    INFRASTRUCTURE = "infrastructure"
    AGENT = "agent"
    EVALUATION = "evaluation"
    CANCELLED = "cancelled"


class AKBenchmarkError(Exception):
    """Base class for all AK-Bench errors."""

    failure_class = FailureClass.INFRASTRUCTURE

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class ConfigError(AKBenchmarkError):
    """Configuration file or environment override is invalid."""

    failure_class = FailureClass.CONFIGURATION


class DatabaseError(AKBenchmarkError):
    """Database is unreachable, uninitialized or not at the expected revision."""

    failure_class = FailureClass.INFRASTRUCTURE


class WorkspaceError(AKBenchmarkError):
    """A run workspace could not be prepared."""

    failure_class = FailureClass.INFRASTRUCTURE


class DoctorFailure(AKBenchmarkError):
    """One or more environment checks failed."""

    failure_class = FailureClass.INFRASTRUCTURE
