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
        parameters = overrides.pop("parameters", None) or {}
        return AgentConfig(
            agent_id="fake",
            parameters=dict(parameters),
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


class TestFakeAgentBehaviours:
    """The scripted behaviours, the per-run override and the alias resolution.

    The contract suite above proves the adapter satisfies the contract; these
    tests prove the fake does what it claims to do, which is the whole point
    of a reference agent: a comparison can rely on its output exactly.
    """

    def _run(self, tmp_path: Path, **overrides: object) -> tuple[FakeAdapter, AgentConfig]:
        profile = FakeContractProfile(tmp_path=tmp_path)
        adapter = profile.make_adapter(**overrides)
        config = profile.make_config()
        session = adapter.start_session(config, profile.workspace())
        adapter.submit_task(session, profile.task())
        return adapter, session

    def test_complete_writes_the_workspace_marker(self, tmp_path: Path) -> None:
        adapter, session = self._run(tmp_path, behaviour="complete")
        result = adapter.wait_for_completion(session, timeout=10)
        assert result.status.value == "completed"
        assert (session.workspace / "AKBENCH_FAKE_RUN.txt").is_file()
        assert result.workspace_changes == ["AKBENCH_FAKE_RUN.txt"]

    def test_noop_completes_without_touching_the_workspace(self, tmp_path: Path) -> None:
        adapter, session = self._run(tmp_path, behaviour="noop")
        result = adapter.wait_for_completion(session, timeout=10)
        assert result.status.value == "completed"
        assert not (session.workspace / "AKBENCH_FAKE_RUN.txt").exists()
        assert result.workspace_changes == []

    def test_alias_names_resolve_to_the_same_behaviour(self, tmp_path: Path) -> None:
        from fake_agent import resolve_behaviour

        assert resolve_behaviour("solve") == "complete"
        assert resolve_behaviour("timeout") == "hang"
        with pytest.raises(ValueError, match="unknown fake behaviour"):
            resolve_behaviour("explode")

    def test_per_run_behaviour_parameter_overrides_the_adapter(self, tmp_path: Path) -> None:
        """An experiment re-scripts one run through the config parameter."""
        profile = FakeContractProfile(tmp_path=tmp_path)
        adapter = profile.make_adapter(behaviour="fail")
        config = profile.make_config(parameters={"behaviour": "noop"})
        session = adapter.start_session(config, profile.workspace())
        adapter.submit_task(session, profile.task())
        result = adapter.wait_for_completion(session, timeout=10)
        assert result.status.value == "completed"
        assert not (session.workspace / "AKBENCH_FAKE_RUN.txt").exists()

    def test_unknown_behaviour_parameter_is_refused(self, tmp_path: Path) -> None:
        profile = FakeContractProfile(tmp_path=tmp_path)
        adapter = profile.make_adapter()
        config = profile.make_config(parameters={"behaviour": "explode"})
        with pytest.raises(ValueError, match="unknown fake behaviour"):
            adapter.start_session(config, profile.workspace())
