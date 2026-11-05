"""Runtime / router descriptor (plan sections 7 and 13).

An agent may run ``direct``, behind a runtime, or through a router. The router
is an optional execution layer, never part of the agent definition, so its
descriptor lives here and references the router rather than the reverse.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from akbench.descriptors.base import DescriptorBase
from akbench.descriptors.statuses import CapabilityStatus


class ExecutionMode(StrEnum):
    DIRECT = "direct"
    RUNTIME = "runtime"
    ROUTER = "router"


class Lifecycle(StrEnum):
    """Who owns the runtime process (plan 7.2, 13)."""

    MANAGED = "managed"
    EXTERNAL = "external"


class RouterCapabilities(BaseModel):
    """What AK-Bench can actually do against this router.

    These are evidence-backed claims about an interface, so they share the
    vocabulary of ``docs/ROUTER_INTEGRATION.md``: ``verified`` means we saw it
    work, ``unsupported`` means the interface refuses it, ``unverified`` means
    nobody looked yet.
    """

    model_config = ConfigDict(extra="forbid")

    healthcheck: CapabilityStatus = CapabilityStatus.UNVERIFIED
    model_inventory: CapabilityStatus = CapabilityStatus.UNVERIFIED
    effective_configuration_read: CapabilityStatus = CapabilityStatus.UNVERIFIED
    configuration_write: CapabilityStatus = CapabilityStatus.UNVERIFIED
    per_run_plugin_control: CapabilityStatus = CapabilityStatus.UNVERIFIED
    plugin_activity_signals: CapabilityStatus = CapabilityStatus.UNVERIFIED
    model_identification: CapabilityStatus = CapabilityStatus.UNVERIFIED
    logs: CapabilityStatus = CapabilityStatus.UNVERIFIED


class ManagedLaunch(BaseModel):
    """How AK-Bench starts a runtime instance it owns (``lifecycle: managed``).

    The command is the instance itself, not a supervisor of it: AK-Bench holds
    the process and stops it with SIGTERM, so a launcher that forks the real
    server (a ``server start`` daemon) would survive its own stop. Environment
    values are declared here rather than exported by hand, because a managed
    instance is the one place where a plugin toggle can be *applied* instead of
    only asked for (plan section 13).
    """

    model_config = ConfigDict(extra="forbid")

    command: list[str] = Field(default_factory=list)
    #: Working directory of the launched process; the router resolves its
    #: models config and prompt directory against it.
    cwd: str | None = None
    #: Static environment of the process (router endpoints, pipeline, toggles).
    env: dict[str, str] = Field(default_factory=dict)
    #: Factor id -> environment variable that carries it, e.g.
    #: ``knowledge_enabled: LLM_ROUTER_KNOWLEDGE_AGENTIC_ENABLED``.
    factor_env: dict[str, str] = Field(default_factory=dict)
    #: Model configuration the process loads; the only readable source of the
    #: effective configuration (there is no configuration read endpoint).
    config_file: str | None = None
    #: Seconds to wait for the instance to become healthy. Verbose mode alone
    #: adds a warning delay, and plugins load embeddings at startup.
    ready_timeout: float = 180.0
    stop_grace: float = 20.0
    #: File name of the instance log, placed in the run's artifacts dir; the
    #: process output is discarded only when this is explicitly set to null.
    log_file: str | None = "router.log"

    @model_validator(mode="after")
    def _check_command(self) -> ManagedLaunch:
        if not self.command:
            raise ValueError("managed.command must name the process to launch")
        return self


class RuntimeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter: str = Field(..., min_length=1)
    execution_modes: list[ExecutionMode] = Field(default_factory=lambda: [ExecutionMode.DIRECT])
    supported_lifecycles: list[Lifecycle] = Field(default_factory=lambda: [Lifecycle.MANAGED])
    base_url: str | None = None
    healthcheck_path: str | None = None
    metrics_path: str | None = None
    configuration_sources: list[str] = Field(default_factory=list)
    capabilities: RouterCapabilities = Field(default_factory=RouterCapabilities)
    required_env: list[str] = Field(default_factory=list)
    #: How to launch this runtime when AK-Bench owns the process. Declaring it
    #: without declaring ``managed`` as a supported lifecycle is a descriptor
    #: error: nothing would ever start it.
    managed: ManagedLaunch | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check_managed_lifecycle(self) -> RuntimeBody:
        if self.managed is not None and Lifecycle.MANAGED not in self.supported_lifecycles:
            raise ValueError(
                "runtime.managed is declared but 'managed' is not in "
                "runtime.supported_lifecycles, so nothing could ever start it"
            )
        return self


class RuntimeDescriptor(DescriptorBase):
    """A runtime or router that can host agents."""

    runtime: RuntimeBody

    def supports_mode(self, mode: ExecutionMode | str) -> bool:
        return ExecutionMode(mode) in self.runtime.execution_modes

    def supports_lifecycle(self, lifecycle: Lifecycle | str) -> bool:
        return Lifecycle(lifecycle) in self.runtime.supported_lifecycles
