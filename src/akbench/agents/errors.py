"""Errors of the agent layer."""

from __future__ import annotations

from akbench.core.errors import AKBenchmarkError


class AgentError(AKBenchmarkError):
    """Base class for everything that can go wrong in an adapter."""


class AgentConfigError(AgentError):
    """The agent configuration does not satisfy the adapter or the environment."""


class SessionClosed(AgentError):
    """An operation was attempted on a session that has already been closed."""


class CapabilityNotSupported(AgentError):
    """The adapter declares a capability it cannot actually provide.

    Raised only when an operation is attempted that the descriptor marks
    ``unsupported``; adapters must fail loudly instead of faking a result.
    """
