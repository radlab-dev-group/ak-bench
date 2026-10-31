"""Runtime registry and execution-mode resolution (plan 7.1 and 7.2)."""

from __future__ import annotations

import pytest

from akbench.descriptors.runtime import (
    Lifecycle,
    RuntimeDescriptor,
)
from akbench.runtime import (
    ExecutionMode,
    RuntimeRegistry,
    build_runtime_registry,
    default_manager_factory,
    plan_execution,
)
from akbench.runtime.errors import RuntimeError

DESCRIPTOR = """\
schema_version: "1.0"
id: sample-router
version: "1.0.0"
title: Sample Router
runtime:
  adapter: llm_router
  execution_modes: [direct, runtime, router]
  supported_lifecycles: [managed, external]
  base_url: http://router.example:1
  healthcheck_path: /health
  metrics_path: /metrics
  required_env: [SOME_ROUTER_KEY]
"""


def descriptor() -> RuntimeDescriptor:
    import yaml

    return RuntimeDescriptor.model_validate(yaml.safe_load(DESCRIPTOR))


def registry() -> RuntimeRegistry:
    return build_runtime_registry([descriptor()])


def test_register_and_resolve() -> None:
    reg = registry()
    entry = reg.resolve("sample-router")
    assert entry.adapter_id == "llm_router"
    assert entry.identity == "sample-router@1.0.0"
    assert len(reg) == 1


def test_unknown_adapter_is_refused() -> None:
    import yaml

    broken = RuntimeDescriptor.model_validate(
        yaml.safe_load(DESCRIPTOR.replace("llm_router", "ghost_adapter"))
    )
    with pytest.raises(
        RuntimeError, match=r"declares adapter 'ghost_adapter', which is not implemented"
    ):
        build_runtime_registry([broken])


def test_unimplemented_adapter_can_be_listed_but_not_used() -> None:
    import yaml

    broken = RuntimeDescriptor.model_validate(
        yaml.safe_load(DESCRIPTOR.replace("llm_router", "ghost_adapter"))
    )
    reg = build_runtime_registry([broken], allow_missing_adapter=True)
    with pytest.raises(RuntimeError, match="no implementation"):
        reg.resolve("sample-router").manager()


def test_direct_mode_must_not_name_a_runtime() -> None:
    reg = registry()
    plan = plan_execution("direct", None, reg)
    assert plan.mode is ExecutionMode.DIRECT
    assert plan.runtime is None
    assert plan.binding is None

    with pytest.raises(RuntimeError, match="must not name a runtime"):
        plan_execution("direct", "sample-router", reg)


def test_router_mode_requires_a_runtime() -> None:
    reg = registry()
    with pytest.raises(RuntimeError, match="requires --runtime"):
        plan_execution("router", None, reg)


def test_router_mode_resolves_the_binding() -> None:
    reg = registry()
    plan = plan_execution("router", "sample-router", reg)
    assert plan.mode is ExecutionMode.ROUTER
    assert plan.runtime is not None
    assert plan.binding.base_url == "http://router.example:1"
    assert plan.binding.api_key_env == "SOME_ROUTER_KEY"
    assert plan.as_dict()["runtime"] == "sample-router@1.0.0"


def test_mode_not_supported_by_the_runtime_is_refused() -> None:
    import yaml

    direct_only = RuntimeDescriptor.model_validate(
        yaml.safe_load(DESCRIPTOR.replace("[direct, runtime, router]", "[direct]"))
    )
    reg = build_runtime_registry([direct_only])
    with pytest.raises(RuntimeError, match="does not support mode"):
        plan_execution("router", "sample-router", reg)


def test_lifecycle_gate() -> None:
    import yaml

    external_only = RuntimeDescriptor.model_validate(
        yaml.safe_load(DESCRIPTOR.replace("[managed, external]", "[external]"))
    )
    reg = build_runtime_registry([external_only])
    with pytest.raises(RuntimeError, match="does not support lifecycle"):
        plan_execution("router", "sample-router", reg, lifecycle=Lifecycle.MANAGED)
    plan = plan_execution("router", "sample-router", reg, lifecycle=Lifecycle.EXTERNAL)
    assert plan.runtime is not None


def test_default_manager_factory_injects_options() -> None:
    factory = default_manager_factory("llm_router", {"base_url": "http://x:9"})
    manager = factory(descriptor())
    assert manager.base_url == "http://x:9"
    assert manager.lifecycle is Lifecycle.EXTERNAL
