"""Errors raised while loading, validating or planning an experiment."""

from __future__ import annotations

from akbench.core.errors import AKBenchmarkError


class ExperimentError(AKBenchmarkError):
    """An experiment descriptor could not be loaded or used."""


class ExperimentValidationError(ExperimentError):
    """The descriptor is malformed or describes an impossible experiment.

    Plan 12.1: an invalid descriptor blocks the run, so this is raised before
    any task, workspace or agent is touched.
    """
