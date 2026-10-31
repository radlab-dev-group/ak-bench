"""The universal agent contract: normalized results and capability gating."""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "contract"))

from fake_agent import FakeAdapter

from akbench.agents.contract import (
    AgentAdapter,
    AgentConfig,
    AgentResult,
    AgentStatus,
    FailureClass,
    RuntimeBinding,
    TokenUsage,
)

UNIVERSAL_KEYS = {
    "agent_id",
    "agent_version",
    "session_id",
    "status",
    "started_at",
    "finished_at",
    "final_message",
    "exit_code",
    "workspace_changes",
    "observations",
    "artifacts",
}


def test_reference_adapter_satisfies_the_protocol() -> None:
    """The contract is a structural one: any matching object is usable."""
    assert isinstance(FakeAdapter(), AgentAdapter)


def test_usage_keeps_unknown_fields_none() -> None:
    usage = TokenUsage(input_tokens=10)
    payload = usage.as_dict()
    assert payload["input_tokens"] == 10
    assert payload["output_tokens"] is None
    assert payload["total_tokens"] is None


def test_result_carries_the_plan_shape(tmp_path: Path) -> None:
    result = AgentResult(
        agent_id="codex",
        agent_version=None,
        session_id=None,
        status=AgentStatus.COMPLETED,
        started_at=1_700_000_000.0,
        finished_at=1_700_000_010.0,
    )
    payload = result.as_dict()

    assert set(payload) >= UNIVERSAL_KEYS
    assert payload["agent_version"] is None
    assert payload["session_id"] is None
    assert payload["final_message"] is None
    assert payload["exit_code"] is None
    assert payload["observations"] == {}
    assert payload["artifacts"] == {}
    assert payload["status"] == "completed"
    assert result.duration_seconds == 10.0


def test_timestamps_are_iso_8601() -> None:
    result = AgentResult(
        agent_id="a",
        agent_version=None,
        session_id=None,
        status=AgentStatus.COMPLETED,
        started_at=1_700_000_000.0,
        finished_at=1_700_000_001.0,
    )
    pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}$"
    assert re.match(pattern, result.as_dict()["started_at"])
    assert re.match(pattern, result.as_dict()["finished_at"])


def test_missing_timestamps_do_not_produce_a_duration() -> None:
    result = AgentResult(
        agent_id="a", agent_version=None, session_id=None, status=AgentStatus.PENDING
    )
    assert result.duration_seconds is None
    assert result.as_dict()["started_at"] is None


def test_status_vocabulary_is_closed() -> None:
    assert {status.value for status in AgentStatus} == {
        "pending",
        "running",
        "completed",
        "failed",
        "timeout",
        "cancelled",
        "infrastructure_error",
    }


def test_failure_classes_separate_agent_from_environment() -> None:
    assert {item.value for item in FailureClass} == {"agent", "infrastructure"}


def test_config_lookup_uses_defaults() -> None:
    config = AgentConfig(agent_id="a", parameters={"model": "m"})
    assert config.get("model") == "m"
    assert config.get("missing", "fallback") == "fallback"


def test_runtime_binding_is_a_plain_declared_fact() -> None:
    binding = RuntimeBinding(runtime_id="r", base_url="http://host:1", api_key_env="KEY")
    assert binding.env == {}
    assert binding.api_key_env == "KEY"
