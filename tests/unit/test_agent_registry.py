"""Agent Registry and catalog: registration, resolution and capability gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from akbench.agents.catalog import (
    ADAPTER_TYPES,
    build_agent_registry,
    default_factory,
)
from akbench.agents.contract import (
    AgentConfig,
    AgentResult,
    AgentSession,
    AgentStatus,
)
from akbench.agents.errors import AgentError
from akbench.agents.registry import AgentRegistry, validate_agent_config
from akbench.descriptors.agent import AgentDescriptor
from akbench.descriptors.registry import DescriptorKind


class SampleAdapter:
    """Tiny stand-in so the registry tests do not depend on the catalog map."""

    adapter_id = "sample_cli"

    def __init__(self, descriptor: AgentDescriptor | None = None) -> None:
        self.descriptor = descriptor

    def validate_environment(self, config: AgentConfig) -> None:
        return None

    def start_session(self, config: AgentConfig, workspace: object) -> AgentSession:
        return AgentSession(adapter_id=self.adapter_id, agent_id=config.agent_id)

    def submit_task(self, session: AgentSession, task: str) -> None:
        return None

    def wait_for_completion(self, session: AgentSession, timeout: float | None) -> AgentResult:
        return AgentResult(
            agent_id=session.agent_id,
            agent_version=None,
            session_id=None,
            status=AgentStatus.COMPLETED,
        )

    def get_status(self, session: AgentSession) -> AgentStatus:
        return AgentStatus.COMPLETED

    def collect_observations(self, session: AgentSession) -> dict:
        return {}

    def cancel(self, session: AgentSession) -> None:
        return None

    def close_session(self, session: AgentSession) -> AgentResult:
        session.closed = True
        return AgentResult(
            agent_id=session.agent_id,
            agent_version=None,
            session_id=None,
            status=AgentStatus.COMPLETED,
        )


def sample_factory():
    return default_factory("sample_cli", adapter_class_=SampleAdapter)

DESCRIPTOR = (
    "schema_version: '1.0'\n"
    "id: sample\n"
    "version: '1.0.0'\n"
    "title: Sample\n"
    "agent:\n"
    "  adapter: sample_cli\n"
    "  execution_type: process\n"
    "  capabilities:\n"
    "    task_submission: verified\n"
    "    cancellation: partial\n"
    "    token_usage: verified\n"
    "    cost_usage: unsupported\n"
    "  configuration_schema:\n"
    "    model:\n"
    "      type: string\n"
    "      controllable: true\n"
    "    sandbox_mode:\n"
    "      type: string\n"
    "      controllable: true\n"
    "      allowed: [read-only, workspace-write]\n"
    "    effort:\n"
    "      type: string\n"
    "      controllable: false\n"
)


def descriptor(version: str = "1.0.0") -> AgentDescriptor:
    import yaml

    document = yaml.safe_load(DESCRIPTOR.replace("1.0.0", version))
    return AgentDescriptor.model_validate(document)


def test_register_and_resolve_newest_version() -> None:
    registry = AgentRegistry()
    registry.register(descriptor("1.0.0"), sample_factory())
    registry.register(descriptor("2.0.0"), sample_factory())

    assert len(registry) == 2
    assert registry.resolve("sample").descriptor.version == "2.0.0"
    assert registry.resolve("sample", "1.0.0").descriptor.version == "1.0.0"
    assert registry.entries()[0].identity == "sample@1.0.0"


def test_resolve_unknown_agent_raises() -> None:
    with pytest.raises(AgentError, match="no agent registered"):
        AgentRegistry().resolve("ghost")


def test_re_registering_replaces_the_entry() -> None:
    registry = AgentRegistry()
    first = registry.register(descriptor(), sample_factory())
    second = registry.register(descriptor(), sample_factory())
    assert len(registry) == 1
    assert first.descriptor.version == second.descriptor.version


def test_capability_gate_uses_declared_status() -> None:
    registry = AgentRegistry()
    entry = registry.register(descriptor(), sample_factory())

    assert entry.check_capabilities(["task_submission"]) == []
    assert entry.check_capabilities(["cost_usage"]) == ["cost_usage"]
    # partial is usable; unverified/absent are not
    assert entry.check_capabilities(["cancellation"]) == []
    assert entry.check_capabilities(["session_reset"]) == ["session_reset"]


def test_factory_builds_a_fresh_adapter_per_call() -> None:
    registry = AgentRegistry()
    registry.register(descriptor(), sample_factory())
    entry = registry.resolve("sample")
    assert entry.adapter() is not entry.adapter()


def test_build_agent_registry_from_descriptors_on_disk() -> None:
    from akbench.agents.codex import CodexAdapter
    from akbench.descriptors.registry import load_descriptor_file as _load

    codex_path = Path(__file__).resolve().parents[2] / "descriptors" / "agents" / "codex.yaml"
    registry = _load(codex_path, DescriptorKind.AGENT)
    codex = registry.get(DescriptorKind.AGENT, "codex")
    assert codex is not None
    agent_registry = build_agent_registry([codex.descriptor])
    assert agent_registry.resolve("codex").adapter_id == "codex_cli"
    assert isinstance(agent_registry.resolve("codex").adapter(), CodexAdapter)
    assert CodexAdapter.adapter_id in ADAPTER_TYPES


def test_unknown_adapter_is_refused_at_build_time() -> None:
    with pytest.raises(AgentError, match="not implemented"):
        build_agent_registry([descriptor()])


def test_unimplemented_adapter_can_be_listed_but_not_used() -> None:
    registry = build_agent_registry([descriptor()], allow_missing_adapter=True)
    entry = registry.resolve("sample")
    with pytest.raises(AgentError, match="no implementation"):
        entry.adapter()


def test_config_validation_rejects_undeclared_parameter() -> None:
    with pytest.raises(AgentError, match="unknown configuration parameter"):
        validate_agent_config(descriptor(), AgentConfig(agent_id="sample", parameters={"nope": 1}))


def test_config_validation_rejects_non_controllable_parameter() -> None:
    with pytest.raises(AgentError, match="not controllable"):
        validate_agent_config(
            descriptor(), AgentConfig(agent_id="sample", parameters={"effort": "high"})
        )


def test_config_validation_enforces_allowed_values() -> None:
    with pytest.raises(AgentError, match="not in the allowed set"):
        validate_agent_config(
            descriptor(),
            AgentConfig(agent_id="sample", parameters={"sandbox_mode": "danger-full-access"}),
        )


def test_config_validation_enforces_declared_type() -> None:
    with pytest.raises(AgentError, match="does not match declared type"):
        validate_agent_config(descriptor(), AgentConfig(agent_id="sample", parameters={"model": 7}))


def test_config_validation_accepts_declared_values() -> None:
    validate_agent_config(
        descriptor(),
        AgentConfig(
            agent_id="sample",
            parameters={"model": "m", "sandbox_mode": "read-only"},
        ),
    )
