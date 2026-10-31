"""Descriptor system: validated, versioned definitions of extensible components.

Every kind inherits the ``schema_version`` / ``id`` / ``version`` identity and
is loaded through :class:`~akbench.descriptors.registry.DescriptorRegistry`, so
a new agent, runtime, plugin or category never requires engine changes.
"""

from __future__ import annotations

from akbench.descriptors.agent import (
    AgentBody,
    AgentDescriptor,
    AgentObservability,
    ConfigurationParameter,
    ExecutionType,
)
from akbench.descriptors.base import SCHEMA_VERSION, DescriptorBase
from akbench.descriptors.category import CategoryBody, CategoryDescriptor
from akbench.descriptors.dimension import DimensionBody, DimensionDescriptor, DimensionType
from akbench.descriptors.env import assert_allowlisted, observe_env, redact
from akbench.descriptors.evaluator import EvaluatorBody, EvaluatorDescriptor, EvaluatorKind
from akbench.descriptors.metric import (
    Availability,
    Direction,
    MetricBody,
    MetricDescriptor,
    MetricGroup,
)
from akbench.descriptors.model import ModelBody, ModelDescriptor, ModelSelection
from akbench.descriptors.plugin import (
    ActivationMethod,
    BenchmarkBlock,
    ConfiguredValue,
    EnvRole,
    EnvType,
    ObservedEnv,
    PluginActivation,
    PluginBody,
    PluginDescriptor,
    PluginState,
    PluginVerification,
)
from akbench.descriptors.registry import (
    DESCRIPTOR_MODELS,
    DescriptorKind,
    DescriptorRegistry,
    DescriptorSnapshot,
    LoadedDescriptor,
    compute_digest,
    iter_descriptor_files,
    load_descriptor_file,
    load_registry,
)
from akbench.descriptors.runtime import (
    ExecutionMode,
    Lifecycle,
    RouterCapabilities,
    RuntimeBody,
    RuntimeDescriptor,
)
from akbench.descriptors.statuses import (
    CapabilityStatus,
    SupportLevel,
    ValueSource,
    VerificationStatus,
)

__all__ = [
    "DESCRIPTOR_MODELS",
    "SCHEMA_VERSION",
    "ActivationMethod",
    "AgentBody",
    "AgentDescriptor",
    "AgentObservability",
    "Availability",
    "BenchmarkBlock",
    "CapabilityStatus",
    "CategoryBody",
    "CategoryDescriptor",
    "ConfigurationParameter",
    "ConfiguredValue",
    "DescriptorBase",
    "DescriptorKind",
    "DescriptorRegistry",
    "DescriptorSnapshot",
    "DimensionBody",
    "DimensionDescriptor",
    "DimensionType",
    "Direction",
    "EnvRole",
    "EnvType",
    "EvaluatorBody",
    "EvaluatorDescriptor",
    "EvaluatorKind",
    "ExecutionMode",
    "ExecutionType",
    "Lifecycle",
    "LoadedDescriptor",
    "MetricBody",
    "MetricDescriptor",
    "MetricGroup",
    "ModelBody",
    "ModelDescriptor",
    "ModelSelection",
    "ObservedEnv",
    "PluginActivation",
    "PluginBody",
    "PluginDescriptor",
    "PluginState",
    "PluginVerification",
    "RouterCapabilities",
    "RuntimeBody",
    "RuntimeDescriptor",
    "SupportLevel",
    "ValueSource",
    "VerificationStatus",
    "assert_allowlisted",
    "compute_digest",
    "iter_descriptor_files",
    "load_descriptor_file",
    "load_registry",
    "observe_env",
    "redact",
]
