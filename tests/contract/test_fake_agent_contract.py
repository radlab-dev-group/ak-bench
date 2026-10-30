"""Contract suite for the reference adapter.

The fake adapter is the smallest implementation of the contract that exists,
so if the suite passes here, the contract itself is implementable without any
knowledge of a real agent. The suite doubles as living documentation of what
an adapter must do.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from adapter_contract import AgentContractSuite
from fake_agent import FakeAdapter

from akbench.agents.contract import AgentConfig


class FakeContractProfile:
    """Contract profile for :class:`FakeAdapter`, fully in-memory."""

    one_shot = True
    supports_cancellation = True
    requires_runtime_binding = False
    reports_infrastructure_separately = True
    reports_usage = True
    reports_version = True

    def __init__(self, tmp_path: Path, behaviour: str = "complete") -> None:
        self.tmp_path = tmp_path
        self.behaviour = behaviour
        self.workspace_dir = tmp_path / "workspace"
        self.workspace_dir.mkdir(exist_ok=True)

    def make_adapter(self, **overrides: object) -> FakeAdapter:
        behaviour = overrides.pop("behaviour", self.behaviour)
        return FakeAdapter(behaviour=behaviour, **overrides)  # type: ignore[arg-type]

    def make_config(self, **overrides: object) -> AgentConfig:
        return AgentConfig(
            agent_id="fake",
            parameters={},
            artifacts_dir=self.tmp_path / "artifacts",
            **overrides,  # type: ignore[arg-type]
        )

    def workspace(self) -> Path:
        return self.workspace_dir

    def task(self) -> str:
        return "Fix the failing test."

    def task_was_delivered(self, adapter: FakeAdapter, session: object, task: str) -> bool:
        run = session.state.get("run")  # type: ignore[union-attr]
        return getattr(run, "task", None) == task

    def failing(self) -> FakeAdapter:
        return FakeAdapter(behaviour="fail")

    def infrastructure_failure(self) -> FakeAdapter:
        return FakeAdapter(behaviour="infrastructure_error")

    def hanging(self) -> FakeAdapter:
        return FakeAdapter(behaviour="hang")

    def without_usage(self) -> FakeAdapter:
        return FakeAdapter(behaviour="complete", report_usage=False, report_version=False)


class TestFakeAgentContract(AgentContractSuite):
    """The reference adapter must pass the same suite as any real adapter."""

    @pytest.fixture(autouse=True)
    def _bind_profile(self, tmp_path: Path) -> None:
        self.profile = FakeContractProfile(tmp_path=tmp_path)
