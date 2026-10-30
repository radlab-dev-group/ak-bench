"""Runtime / router descriptor (plan sections 7 and 13).

An agent may run ``direct``, behind a runtime, or through a router. The router
is an optional execution layer, never part of the agent definition, so its
descriptor lives here and references the router rather than the reverse.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

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
    notes: str | None = None


class RuntimeDescriptor(DescriptorBase):
    """A runtime or router that can host agents."""

    runtime: RuntimeBody

    def supports_mode(self, mode: ExecutionMode | str) -> bool:
        return ExecutionMode(mode) in self.runtime.execution_modes

    def supports_lifecycle(self, lifecycle: Lifecycle | str) -> bool:
        return Lifecycle(lifecycle) in self.runtime.supported_lifecycles
