"""Agent layer: the universal adapter contract, registry and adapters.

The engine talks only to this package. Everything agent-specific — how a
session is started, how a task is submitted, how completion is detected,
what "a tool call" means — lives inside an adapter, so the runner, the
scheduler and the evaluators never see a concrete agent name (plan 6.1).
"""

from akbench.agents.codex import CodexAdapter
from akbench.agents.contract import (
    AgentAdapter,
    AgentConfig,
    AgentResult,
    AgentSession,
    AgentStatus,
    FailureClass,
    RuntimeBinding,
    TokenUsage,
)
from akbench.agents.errors import (
    AgentConfigError,
    AgentError,
    CapabilityNotSupported,
    SessionClosed,
)
from akbench.agents.registry import AdapterFactory, AgentEntry, AgentRegistry

__all__ = [
    "AdapterFactory",
    "AgentAdapter",
    "AgentConfig",
    "AgentConfigError",
    "AgentEntry",
    "AgentError",
    "AgentRegistry",
    "AgentResult",
    "AgentSession",
    "AgentStatus",
    "CapabilityNotSupported",
    "CodexAdapter",
    "FailureClass",
    "RuntimeBinding",
    "SessionClosed",
    "TokenUsage",
]
