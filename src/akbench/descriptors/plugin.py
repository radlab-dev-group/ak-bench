"""Plugin descriptor and plugin state model (plan section 10).

Two rules drive this module. First, only explicitly declared environment
variables may ever be observed, and a secret is reported as ``is_set`` only
(10.1). Second, the presence of an environment variable or a configuration
entry is *not* proof a plugin works, so requested, configured, effective and
observed values are recorded separately (10.2).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from akbench.descriptors.base import DescriptorBase
from akbench.descriptors.statuses import ValueSource, VerificationStatus


class EnvType(StrEnum):
    BOOLEAN = "boolean"
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    LIST = "list"


class EnvRole(StrEnum):
    FEATURE_TOGGLE = "feature_toggle"
    THRESHOLD = "threshold"
    IDENTIFIER = "identifier"
    INFRASTRUCTURE = "infrastructure"
    SECRET = "secret"


class ObservedEnv(BaseModel):
    """One allowlisted environment variable (plan 10.1)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    type: EnvType = EnvType.STRING
    role: EnvRole = EnvRole.INFRASTRUCTURE
    observed: bool = False
    dimension: bool = False
    controllable: bool = False
    sensitive: bool = False
    default: str | int | float | bool | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _check_flags_are_coherent(self) -> ObservedEnv:
        if self.dimension and not self.controllable:
            raise ValueError(
                f"{self.name}: a dimension must be controllable; uncontrollable "
                "parameters may only be observed, never varied"
            )
        if self.sensitive and self.controllable:
            raise ValueError(f"{self.name}: a sensitive variable must not be controlled")
        if self.role is EnvRole.SECRET:
            self.sensitive = True
        return self

    @property
    def records_value(self) -> bool:
        """Secrets are represented by presence alone, never by content."""
        return not self.sensitive


class ActivationMethod(StrEnum):
    ROUTER_CONFIGURATION = "router_configuration"
    ENVIRONMENT = "environment"
    API = "api"
    CONFIG_FILE = "config_file"
    NONE = "none"


class PluginActivation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: ActivationMethod = ActivationMethod.NONE
    detail: str | None = None


class PluginVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: bool = True
    methods: list[str] = Field(default_factory=list)
    note: str | None = None


class PluginBody(BaseModel):
    """The ``plugin:`` block of a Plugin Descriptor."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)
    capabilities: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)


class BenchmarkBlock(BaseModel):
    """The ``benchmark:`` block: how AK-Bench uses this plugin."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    activation: PluginActivation = Field(default_factory=PluginActivation)
    verification: PluginVerification = Field(default_factory=PluginVerification)
    observed_env: list[ObservedEnv] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def _check_unique_env_names(self) -> BenchmarkBlock:
        seen: set[str] = set()
        for entry in self.observed_env:
            if entry.name in seen:
                raise ValueError(f"duplicate observed_env entry: {entry.name}")
            seen.add(entry.name)
        return self

    def env(self, name: str) -> ObservedEnv | None:
        for entry in self.observed_env:
            if entry.name == name:
                return entry
        return None

    def dimension_names(self) -> list[str]:
        return [entry.name for entry in self.observed_env if entry.dimension]


class PluginDescriptor(DescriptorBase):
    """Identity, capabilities, activation, ENV allowlist and metrics of a plugin."""

    plugin: PluginBody
    benchmark: BenchmarkBlock = Field(default_factory=BenchmarkBlock)

    @property
    def requires_verification(self) -> bool:
        return self.benchmark.verification.required

    def dimension_entries(self) -> list[ObservedEnv]:
        return [entry for entry in self.benchmark.observed_env if entry.dimension]

    def observable_entries(self) -> list[ObservedEnv]:
        return [entry for entry in self.benchmark.observed_env if entry.observed]


class ConfiguredValue(BaseModel):
    """One value in the requested/configured/effective/observed chain."""

    model_config = ConfigDict(extra="forbid")

    name: str
    requested_value: str | int | float | bool | None = None
    configured_value: str | int | float | bool | None = None
    effective_value: str | int | float | bool | None = None
    observed_value: str | int | float | bool | None = None
    is_set: bool | None = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    value_source: ValueSource = ValueSource.UNKNOWN
    note: str | None = None

    @classmethod
    def for_entry(cls, entry: ObservedEnv, **values: object) -> ConfiguredValue:
        return cls(name=entry.name, **values)  # type: ignore[arg-type]

    def redacted(self) -> dict[str, object]:
        """Dump without secret content; presence is kept as ``is_set``."""
        payload = self.model_dump(mode="json")
        value_fields = ("requested_value", "configured_value", "effective_value", "observed_value")
        if self.is_set is None:
            payload["is_set"] = any(self.model_dump()[field] is not None for field in value_fields)
        for field in value_fields:
            payload[field] = None
        return payload


class PluginState(BaseModel):
    """Per-run plugin state; never claims success without verification (10.2)."""

    model_config = ConfigDict(extra="forbid")

    plugin_id: str
    plugin_version: str
    enabled: bool = False
    values: list[ConfiguredValue] = Field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    events_observed: bool = False
    note: str | None = None

    def value(self, name: str) -> ConfiguredValue | None:
        for item in self.values:
            if item.name == name:
                return item
        return None
