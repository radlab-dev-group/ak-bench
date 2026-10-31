"""Errors of the runtime layer."""

from __future__ import annotations

from akbench.core.errors import AKBenchmarkError


class RuntimeError(AKBenchmarkError):
    """Base class for everything that can go wrong with a runtime."""


class RuntimeConfigError(RuntimeError):
    """The runtime configuration is missing, invalid or unsupported."""


class RuntimeNotStarted(RuntimeError):
    """An operation was attempted on a runtime that is not started."""


class CapabilityNotSupported(RuntimeError):
    """The runtime declares a capability it cannot provide.

    A missing capability must surface as an error with the reason, never as a
    fake result (plan section 13: a configuration that cannot be confirmed is
    not active).
    """
