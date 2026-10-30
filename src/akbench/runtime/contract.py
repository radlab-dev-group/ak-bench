"""The runtime manager contract (plan sections 7.2 and 13).

A runtime manager is an adapter for one concrete runtime: it knows how to
start, stop, healthcheck and verify *that* runtime. The engine only sees this
contract, so the router, a local runtime and a future managed instance are
interchangeable at the call sites.

The configuration triad of plan section 13 is first class here:

- ``requested`` — what the experiment asked for;
- ``effective`` — what the runtime actually applies (read from the runtime,
  not from the request);
- ``observed`` — what AK-Bench could actually observe.

They are stored separately and ``verification_status`` says how much trust the
other two deserve. When a runtime cannot be read, the status is
``unsupported`` or ``unverified`` and the fields stay ``None`` — never
guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class ExecutionMode(StrEnum):
    """How an agent reaches its model (plan 7.1). The experiment declares it."""

    DIRECT = "direct"
    RUNTIME = "runtime"
    ROUTER = "router"


class Lifecycle(StrEnum):
    """Who owns the runtime process (plan 7.2, 13)."""

    EXTERNAL = "external"
    MANAGED = "managed"


class VerificationStatus(StrEnum):
    """How much trust a configuration reading deserves (plan rule 11, 13)."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class RuntimeConfigReport:
    """The requested/effective/observed triad plus its trust level.

    ``effective`` is only ever filled from the runtime itself. ``observed`` is
    what AK-Bench could actually confirm. When a field cannot be obtained it
    stays ``None`` and the status says why.
    """

    requested: dict[str, Any] = field(default_factory=dict)
    effective: dict[str, Any] | None = None
    observed: dict[str, Any] = field(default_factory=dict)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested_config": dict(self.requested),
            "effective_config": self.effective,
            "observed_config": dict(self.observed),
            "verification_status": self.verification_status.value,
            "notes": list(self.notes),
        }


@dataclass
class RuntimeState:
    """A point-in-time snapshot of the runtime, from whatever it exposes."""

    healthy: bool | None = None
    base_url: str | None = None
    lifecycle: Lifecycle | None = None
    models: list[str] = field(default_factory=list)
    metrics_available: bool | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "base_url": self.base_url,
            "lifecycle": self.lifecycle.value if self.lifecycle else None,
            "models": list(self.models),
            "metrics_available": self.metrics_available,
            "details": dict(self.details),
        }


@runtime_checkable
class RuntimeManager(Protocol):
    """What every runtime adapter implements (plan 7.2).

    Capability-aware: an operation the runtime cannot support raises
    ``CapabilityNotSupported`` after the descriptor has declared it, instead
    of being faked. ``direct`` mode is represented by no runtime at all, so no
    manager is instantiated for it.
    """

    runtime_id: str
    lifecycle: Lifecycle

    def start(self) -> None:
        """Start a managed runtime. No-op for external runtimes."""
        ...

    def stop(self) -> None:
        """Stop a managed runtime. No-op for external runtimes."""
        ...

    def healthcheck(self) -> bool:
        """Return whether the runtime answers its health endpoint."""
        ...

    def apply_configuration(self, config: dict[str, Any]) -> None:
        """Push a configuration to the runtime, where the interface allows it."""
        ...

    def read_configuration(self) -> RuntimeConfigReport:
        """Read the effective configuration back, reporting its trust level."""
        ...

    def verify_configuration(self, expected: dict[str, Any]) -> RuntimeConfigReport:
        """Compare the effective configuration against an expectation."""
        ...

    def collect_runtime_state(self) -> RuntimeState:
        """Gather whatever the runtime exposes about its own state."""
        ...
