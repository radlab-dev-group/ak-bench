"""The universal agent adapter contract (plan section 6.2 and 6.3).

This module is the only surface the engine is allowed to use. It deliberately
stays small:

- ``AgentConfig`` is the validated, agent-specific configuration block of an
  experiment. The engine passes it through untouched; each adapter knows how
  to interpret its own knobs.
- ``AgentSession`` is an opaque handle. What a "session" means differs per
  agent class (a process, an HTTP conversation, a service lease, a routed
  thread), so the engine must not inspect it (plan 6.5).
- ``AgentStatus`` and ``AgentResult`` normalize the outcome. Fields that an
  agent cannot provide stay ``None``; nothing is ever guessed (plan 6.3).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class AgentStatus(StrEnum):
    """Lifecycle of one agent run, normalized across all adapters."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timeout"
    CANCELLED = "cancelled"
    INFRASTRUCTURE_ERROR = "infrastructure_error"


class FailureClass(StrEnum):
    """Who to blame: the agent under test, or the environment around it.

    Plan rule 11: infrastructure failures must be classified separately from
    agent failures so a benchmark run is never silently invalidated by a
    network blip.
    """

    AGENT = "agent"
    INFRASTRUCTURE = "infrastructure"


@dataclass(frozen=True)
class TokenUsage:
    """Token accounting. Any field may be ``None`` when the agent does not
    report it; adapters must not invent zero when they do not know."""

    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    total_tokens: int | None = None

    def as_dict(self) -> dict[str, int | None]:
        return {
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_output_tokens": self.reasoning_output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class RuntimeBinding:
    """What the runtime layer hands an agent about the endpoint it should use.

    The runner does not know what an endpoint means for a given agent; it only
    forwards this binding, and each adapter translates it into the agent's own
    configuration format (plan 6.2). Phase 5 (Runtime Manager) will produce it
    from a managed or external runtime; today it is built from a Runtime
    Descriptor, so both values are declared facts, never guesses.
    """

    runtime_id: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentConfig:
    """Agent-specific configuration as selected by the experiment.

    ``parameters`` is validated against the agent descriptor's
    ``configuration_schema`` before it reaches the adapter; the adapter still
    re-checks anything it cannot trust (for example values that must exist in
    the agent's own environment).

    ``artifacts_dir`` is where the adapter may write native logs and traces.
    Without it an adapter keeps nothing on disk and reports no artifacts.
    """

    agent_id: str
    parameters: dict[str, Any] = field(default_factory=dict)
    artifacts_dir: Path | None = None
    runtime: RuntimeBinding | None = None

    def get(self, name: str, default: Any = None) -> Any:
        return self.parameters.get(name, default)


@dataclass
class AgentSession:
    """An opaque, adapter-owned handle for one run.

    Adapters store whatever they need in ``state``: a subprocess, a client
    connection, a thread id. The engine only ever passes the handle back.
    """

    adapter_id: str
    agent_id: str
    session_id: str | None = None
    workspace: Path | None = None
    started_at: float = field(default_factory=time.time)
    closed: bool = False
    state: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """The universal, normalized result of one agent run (plan 6.3).

    Every field that the agent cannot provide stays ``None``. The JSON shape
    of the plan is produced by :meth:`as_dict`, so downstream storage and
    reports never depend on an adapter's native format.
    """

    agent_id: str
    agent_version: str | None
    session_id: str | None
    status: AgentStatus
    started_at: float | None = None
    finished_at: float | None = None
    final_message: str | None = None
    exit_code: int | None = None
    failure_class: FailureClass | None = None
    workspace_changes: list[str] = field(default_factory=list)
    observations: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    usage: TokenUsage | None = None

    @property
    def started_at_iso(self) -> str | None:
        return _iso(self.started_at)

    @property
    def finished_at_iso(self) -> str | None:
        return _iso(self.finished_at)

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return round(self.finished_at - self.started_at, 3)

    def as_dict(self) -> dict[str, Any]:
        """The plan's universal JSON shape, plus provenance extras."""
        return {
            "agent_id": self.agent_id,
            "agent_version": self.agent_version,
            "session_id": self.session_id,
            "status": self.status.value,
            "started_at": self.started_at_iso,
            "finished_at": self.finished_at_iso,
            "final_message": self.final_message,
            "exit_code": self.exit_code,
            "failure_class": self.failure_class.value if self.failure_class else None,
            "workspace_changes": list(self.workspace_changes),
            "observations": dict(self.observations),
            "artifacts": dict(self.artifacts),
            "usage": self.usage.as_dict() if self.usage else None,
            "duration_seconds": self.duration_seconds,
        }


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(epoch))


@runtime_checkable
class AgentAdapter(Protocol):
    """What every agent adapter implements (plan 6.2).

    The contract is deliberately capability-aware: an operation the agent
    cannot support must raise ``CapabilityNotSupported`` (after the
    descriptor has said so) rather than be faked. Adapters that cannot even
    distinguish that case may omit it, but the registry records which
    capabilities were actually confirmed (plan 6.4).
    """

    adapter_id: str

    def validate_environment(self, config: AgentConfig) -> None:
        """Check the host can run this agent (binary, env vars, versions).

        Raises ``AgentConfigError`` describing exactly what is missing.
        """
        ...

    def start_session(self, config: AgentConfig, workspace: Path) -> AgentSession:
        """Create a fresh run bound to ``workspace`` (plan 6.4 workspace_binding)."""
        ...

    def submit_task(self, session: AgentSession, task: str) -> None:
        """Hand the task text to the agent. ``task`` is plain text, whatever
        the agent's native interface happens to be."""
        ...

    def wait_for_completion(self, session: AgentSession, timeout: float | None) -> AgentResult:
        """Block until the agent finishes or the timeout elapses.

        A timeout produces a result with ``status=timeout``; the adapter is
        expected to cancel the underlying work.
        """
        ...

    def get_status(self, session: AgentSession) -> AgentStatus:
        """Best-effort lifecycle status of the current run."""
        ...

    def collect_observations(self, session: AgentSession) -> dict[str, Any]:
        """Gather whatever the agent exposes: tool calls, token usage, the
        observed model, session id. Unknown values stay ``None``."""
        ...

    def cancel(self, session: AgentSession) -> None:
        """Ask the agent to stop. Best-effort per the descriptor capability."""
        ...

    def close_session(self, session: AgentSession) -> AgentResult:
        """Release all resources and return the normalized final result."""
        ...
