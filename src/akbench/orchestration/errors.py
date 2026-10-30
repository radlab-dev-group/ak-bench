"""Errors of the run orchestrator."""

from __future__ import annotations

from akbench.core.errors import AKBenchmarkError


class OrchestrationError(AKBenchmarkError):
    """Base class for orchestrator problems."""


class RunPreparationError(OrchestrationError):
    """A run cannot start: configuration, workspace or environment is unusable."""
