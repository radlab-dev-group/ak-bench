"""Errors of the evaluator engine."""

from __future__ import annotations

from akbench.core.errors import AKBenchmarkError


class EvaluationError(AKBenchmarkError):
    """Base class for everything that can go wrong in evaluation."""


class EvaluatorNotFound(EvaluationError):
    """The task's evaluator is not implemented or not registered."""


class EvaluatorExecutionError(EvaluationError):
    """The evaluator could not run.

    This is a failure of the measurement, never of the agent, and must be
    classified as such (plan rule 11).
    """
