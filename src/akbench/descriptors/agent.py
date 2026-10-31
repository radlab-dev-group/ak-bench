"""Agent descriptor (plan sections 6.4 to 6.7).

An agent descriptor declares *what the agent interface can do*, with a status
per capability. The engine must never assume a capability that is not declared
usable here, and must never simulate one that is missing.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from akbench.descriptors.base import DescriptorBase
from akbench.descriptors.statuses import CapabilityStatus, SupportLevel


class ExecutionType(StrEnum):
    """How the agent process or service is reached (plan 6.5)."""

    PROCESS = "process"
    HTTP = "http"
    SERVICE = "service"
    ROUTER_MEDIATED = "router_mediated"


class ConfigurationParameter(BaseModel):
    """One agent configuration knob the experiment may try to control."""

    model_config = ConfigDict(extra="forbid")

    type: str = "string"
    controllable: bool = False
    default: str | int | float | bool | None = None
    allowed: list[str | int | float | bool] | None = None
    applies_via: str | None = None
    verification: str | None = None

    @model_validator(mode="after")
    def _check_allowed_matches_type(self) -> ConfigurationParameter:
        if self.allowed is not None:
            for value in self.allowed:
                if not _type_matches(value, self.type):
                    raise ValueError(
                        f"allowed value {value!r} does not match type {self.type!r}"
                    )
        return self


def _type_matches(value: object, declared: str) -> bool:
    if declared == "boolean":
        return isinstance(value, bool)
    if declared == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, str)


class AgentObservability(BaseModel):
    """What the agent exposes about its own execution."""

    model_config = ConfigDict(extra="forbid")

    session_id: SupportLevel = SupportLevel.UNVERIFIED
    token_usage: SupportLevel = SupportLevel.UNVERIFIED
    cost: SupportLevel = SupportLevel.UNVERIFIED
    tool_calls: SupportLevel = SupportLevel.UNVERIFIED
    model_selection: SupportLevel = SupportLevel.UNVERIFIED
    streaming_output: SupportLevel = SupportLevel.UNVERIFIED
    session_export: SupportLevel = SupportLevel.UNVERIFIED


class AgentBody(BaseModel):
    """The ``agent:`` block of an Agent Descriptor."""

    model_config = ConfigDict(extra="forbid")

    adapter: str = Field(..., min_length=1, description="Adapter implementation id.")
    execution_type: ExecutionType = ExecutionType.PROCESS
    capabilities: dict[str, CapabilityStatus] = Field(default_factory=dict)
    configuration_schema: dict[str, ConfigurationParameter] = Field(default_factory=dict)
    observability: AgentObservability = Field(default_factory=AgentObservability)
    required_tools: list[str] = Field(default_factory=list)
    version_detection: list[str] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("capabilities")
    @classmethod
    def _no_empty_capabilities(
        cls, value: dict[str, CapabilityStatus]
    ) -> dict[str, CapabilityStatus]:
        for name in value:
            if not name.strip():
                raise ValueError("capability names must not be empty")
        return value


class AgentDescriptor(DescriptorBase):
    """Agent identity, adapter, capabilities and controllable configuration."""

    agent: AgentBody

    def capability(self, name: str) -> CapabilityStatus | None:
        return self.agent.capabilities.get(name)

    def requires_usable(self, name: str) -> bool:
        """True only when the capability is declared and evidence-backed."""
        status = self.agent.capabilities.get(name)
        return status is not None and status.usable

    def missing_capabilities(self, required: list[str]) -> list[str]:
        """Capabilities an experiment needs but this agent cannot provide.

        Returns the names that are absent, ``unsupported`` or ``unverified``.
        """
        missing: list[str] = []
        for name in required:
            status = self.agent.capabilities.get(name)
            if status is None or not status.usable:
                missing.append(name)
        return missing

    def controllable_parameters(self) -> list[str]:
        return [
            name
            for name, parameter in self.agent.configuration_schema.items()
            if parameter.controllable
        ]
