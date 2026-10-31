"""Descriptor models: identity, validation rules and derived facts."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from akbench.core.errors import DescriptorError
from akbench.descriptors import (
    AgentDescriptor,
    CategoryDescriptor,
    DimensionDescriptor,
    EvaluatorDescriptor,
    MetricDescriptor,
    ModelDescriptor,
    ObservedEnv,
    PluginDescriptor,
    RuntimeDescriptor,
)

VALIDATION_ERRORS = (ValidationError, DescriptorError)


def test_identity_and_snapshot_are_stable(tmp_path: Path) -> None:
    descriptor = ModelDescriptor(id="qwen3-coder:30b", version="1.0.0")
    assert descriptor.identity() == "qwen3-coder:30b@1.0.0"
    assert descriptor.to_snapshot() == descriptor.to_snapshot()
    assert descriptor.to_snapshot()["schema_version"] == "1.0"


def test_unknown_schema_version_is_rejected() -> None:
    with pytest.raises(VALIDATION_ERRORS):
        ModelDescriptor(id="m", version="1", schema_version="9.9")


def test_unknown_keys_are_rejected() -> None:
    with pytest.raises(VALIDATION_ERRORS):
        ModelDescriptor(id="m", version="1", model={"provider": "x", "not_a_field": 1})


def test_agent_capability_gaps_are_derived() -> None:
    descriptor = AgentDescriptor(
        id="codex",
        version="1",
        agent={
            "adapter": "codex_cli",
            "capabilities": {
                "token_usage": "verified",
                "cost_usage": "unsupported",
                "session_reset": "unverified",
            },
        },
    )
    assert descriptor.requires_usable("token_usage")
    assert not descriptor.requires_usable("cost_usage")
    assert not descriptor.requires_usable("session_reset")
    assert descriptor.missing_capabilities(["cost_usage", "token_usage"]) == ["cost_usage"]


def test_controllable_parameter_requires_matching_allowed_values() -> None:
    descriptor = AgentDescriptor(
        id="a",
        version="1",
        agent={
            "adapter": "x",
            "configuration_schema": {
                "mode": {
                    "type": "string",
                    "controllable": True,
                    "allowed": ["a", "b"],
                }
            },
        },
    )
    assert descriptor.controllable_parameters() == ["mode"]

    with pytest.raises(VALIDATION_ERRORS):
        AgentDescriptor(
            id="a",
            version="1",
            agent={
                "adapter": "x",
                "configuration_schema": {
                    "mode": {
                        "type": "string",
                        "controllable": True,
                        "allowed": ["a", 1],
                    }
                },
            },
        )


def test_dimension_value_space_rules() -> None:
    # Controllable categorical dimensions must declare values.
    with pytest.raises(VALIDATION_ERRORS):
        DimensionDescriptor(
            id="d",
            version="1",
            dimension={"type": "categorical", "controllable": True},
        )

    # Uncontrollable dimensions may be observed-only.
    observed_only = DimensionDescriptor(
        id="routed_model",
        version="1",
        dimension={"type": "model_reference", "controllable": False, "observed": True},
    )
    assert observed_only.usable_as_factor is False
    assert observed_only.accepts("anything") is False

    controllable = DimensionDescriptor(
        id="model",
        version="1",
        dimension={"type": "model_reference", "controllable": True, "values": ["a", "b"]},
    )
    assert controllable.usable_as_factor is True
    assert controllable.accepts("a")
    assert not controllable.accepts("c")

    boolean = DimensionDescriptor(
        id="flag",
        version="1",
        dimension={"type": "boolean", "controllable": True},
    )
    assert boolean.allowed_values() == [False, True]


def test_integer_dimension_bounds_must_be_sane() -> None:
    with pytest.raises(VALIDATION_ERRORS):
        DimensionDescriptor(
            id="r",
            version="1",
            dimension={"type": "integer", "minimum": 5, "maximum": 1},
        )


def test_observed_env_flags_are_coherent() -> None:
    # dimension without controllable is a planning contradiction
    with pytest.raises(VALIDATION_ERRORS):
        ObservedEnv(
            name="X_ENABLED",
            type="boolean",
            dimension=True,
            controllable=False,
        )
    # secrets may never be controlled
    with pytest.raises(VALIDATION_ERRORS):
        ObservedEnv(name="X_TOKEN", type="string", controllable=True, sensitive=True)
    # role=secret implies sensitive
    entry = ObservedEnv(name="X_TOKEN", type="string", role="secret")
    assert entry.sensitive is True
    assert entry.records_value is False


def test_plugin_env_names_must_be_unique() -> None:
    with pytest.raises(VALIDATION_ERRORS):
        PluginDescriptor(
            id="p",
            version="1",
            plugin={"provider": "llm-router", "type": "knowledge"},
            benchmark={
                "observed_env": [
                    {"name": "X_ENABLED", "type": "boolean"},
                    {"name": "X_ENABLED", "type": "boolean"},
                ]
            },
        )


def test_evaluator_kind_is_an_open_enum() -> None:
    evaluator = EvaluatorDescriptor(
        id="pytest_evaluator",
        version="1",
        evaluator={"kind": "pytest"},
    )
    assert evaluator.evaluator.runs_outside_workspace is True
    with pytest.raises(VALIDATION_ERRORS):
        EvaluatorDescriptor(
            id="e",
            version="1",
            evaluator={"kind": "guesswork"},
        )


def test_metric_availability_never_invents_zero() -> None:
    metric = MetricDescriptor(
        id="total_cost",
        version="1",
        metric={
            "group": "efficiency",
            "availability": "unavailable",
            "unavailable_reason": "no cost field exists",
        },
    )
    assert metric.computable is False
    assert metric.metric.unavailable_reason is not None


def test_runtime_capabilities_are_evidence_based() -> None:
    runtime = RuntimeDescriptor(
        id="llm-router",
        version="1",
        runtime={
            "adapter": "llm_router",
            "execution_modes": ["direct", "runtime", "router"],
            "capabilities": {"effective_configuration_read": "unsupported"},
        },
    )
    assert runtime.runtime.capabilities.effective_configuration_read.value == "unsupported"
    assert runtime.supports_mode("router")
    assert not runtime.supports_lifecycle("external")


def test_category_enables_only_declared_difficulties() -> None:
    category = CategoryDescriptor(
        id="performance",
        version="1",
        category={"enabled": False, "difficulties": ["hard", "expert"]},
    )
    assert category.allows_difficulty("hard") is False
    assert category.category.enabled is False
