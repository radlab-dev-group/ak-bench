"""Contract suite for the Codex adapter, driven by the CLI stub.

The adapter under test is the production one; only the CLI is a stub. That way
these tests prove the adapter's own behaviour — event parsing, rollout reading,
timeout escalation, cancellation, status normalization — without an agent, a
router or a network. The live check against the real CLI is separate
(``test_codex_live_contract.py``) and skipped unless explicitly enabled.
"""

from __future__ import annotations

import json
import shutil
import stat
from pathlib import Path
from typing import Any

import pytest
from adapter_contract import AgentContractSuite

from akbench.agents.codex import CodexAdapter, CodexOptions
from akbench.agents.contract import AgentConfig, AgentSession
from akbench.descriptors import AgentDescriptor, DescriptorKind, load_descriptor_file

REPO_ROOT = Path(__file__).resolve().parents[2]
STUB = Path(__file__).parent / "stubs" / "codex_stub.py"


def load_codex_descriptor() -> AgentDescriptor:
    registry = load_descriptor_file(
        REPO_ROOT / "descriptors" / "agents" / "codex.yaml",
        DescriptorKind.AGENT,
    )
    loaded = registry.get(DescriptorKind.AGENT, "codex")
    assert loaded is not None, "the codex agent descriptor must exist"
    return loaded.descriptor


class CodexContractProfile:
    """Runs the real adapter against the stub CLI, one scratch directory per test."""

    one_shot = True
    supports_cancellation = True
    requires_runtime_binding = True
    reports_infrastructure_separately = True
    reports_usage = True
    reports_version = True

    def __init__(self, tmp_path: Path, stub_log: Path) -> None:
        self.tmp_path = tmp_path
        self.stub_log = stub_log
        self.descriptor = load_codex_descriptor()

    def make_adapter(self, behaviour: str = "complete") -> CodexAdapter:
        return CodexAdapter(
            self.descriptor,
            CodexOptions(
                binary=self.stub_binary(),
                extra_args=("--stub-behaviour", behaviour),
                interrupt_grace=2.0,
                terminate_grace=1.0,
            ),
        )

    def stub_binary(self) -> str:
        bin_dir = self.tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        target = bin_dir / "codex"
        if not target.is_file():
            shutil.copyfile(STUB, target)
            target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP)
        return str(target)

    def make_config(self, **overrides: Any) -> AgentConfig:
        parameters: dict[str, Any] = {"sandbox_mode": "read-only", "approval_policy": "never"}
        parameters.update(overrides.pop("parameters", {}))
        overrides.setdefault("artifacts_dir", self.tmp_path / "artifacts")
        return AgentConfig(
            agent_id="codex",
            parameters=parameters,
            **overrides,
        )

    def workspace(self) -> Path:
        workspace = self.tmp_path / "workspace"
        workspace.mkdir(exist_ok=True)
        return workspace

    def task(self) -> str:
        return "Repair the failing word count test."

    def task_was_delivered(self, adapter: Any, session: AgentSession, task: str) -> bool:
        if not self.stub_log.is_file():
            return False
        for line in self.stub_log.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record["prompt"] == task and Path(record["cwd"]) == session.workspace:
                return True
        return False

    def failing(self) -> CodexAdapter:
        return self.make_adapter("fail")

    def infrastructure_failure(self) -> CodexAdapter:
        return self.make_adapter("infra_error")

    def hanging(self) -> CodexAdapter:
        return self.make_adapter("hang")

    def without_usage(self) -> CodexAdapter:
        return self.make_adapter("no_usage")


class TestCodexAdapterContract(AgentContractSuite):
    """The phase 4 gate: Codex is reachable through the contract only."""

    @pytest.fixture(autouse=True)
    def _bind_profile(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log = tmp_path / "stub_invocations.jsonl"
        monkeypatch.setenv("STUB_LOG", str(log))
        self.profile = CodexContractProfile(tmp_path=tmp_path, stub_log=log)

    def test_agent_config_is_written_into_a_private_home(self) -> None:
        """Isolation recipe: one CODEX_HOME per run, provider via env_key."""
        adapter = self.profile.make_adapter()
        session = adapter.start_session(self.profile.make_config(), self.profile.workspace())

        home = Path(session.state["run"].home)
        assert home.is_dir()
        assert session.state["run"].env["CODEX_HOME"] == str(home)
        config = (home / "config.toml").read_text(encoding="utf-8")
        assert "sandbox_mode" in config
        assert "approval_policy" in config

    def test_sandbox_mode_reaches_the_command_line(self) -> None:
        adapter = self.profile.make_adapter()
        config = self.profile.make_config(parameters={"sandbox_mode": "workspace-write"})
        session = adapter.start_session(config, self.profile.workspace())
        adapter.submit_task(session, self.profile.task())
        adapter.wait_for_completion(session, timeout=20)

        record = json.loads(self.profile.stub_log.read_text(encoding="utf-8").splitlines()[-1])
        argv = record["argv"]
        assert argv[argv.index("-s") + 1] == "workspace-write"

    def test_isolation_gives_each_run_its_own_home(self) -> None:
        adapter = self.profile.make_adapter()
        first = adapter.start_session(
            self.profile.make_config(artifacts_dir=self.profile.tmp_path / "run-a"),
            self.profile.workspace(),
        )
        second = adapter.start_session(
            self.profile.make_config(artifacts_dir=self.profile.tmp_path / "run-b"),
            self.profile.workspace(),
        )

        assert first.state["run"].home != second.state["run"].home

    def test_rollout_observations_are_read_from_the_agent_home(self) -> None:
        adapter = self.profile.make_adapter()
        session = adapter.start_session(self.profile.make_config(), self.profile.workspace())
        adapter.submit_task(session, self.profile.task())
        result = adapter.wait_for_completion(session, timeout=20)

        observations = result.observations
        assert observations["session_id"] == "stub-thread-1"
        assert observations["observed_model"] == "stub-model-alias"
        assert observations["observed_sandbox"] == "workspace-write"
        assert observations["tool_call_count"] == 2
        assert observations["rollout_available"] is True
        assert result.usage is not None
        assert result.usage.input_tokens == 120
        assert result.usage.reasoning_output_tokens == 6

    def test_agent_version_comes_from_the_cli_not_the_descriptor(self) -> None:
        adapter = self.profile.make_adapter()
        session = adapter.start_session(self.profile.make_config(), self.profile.workspace())
        adapter.submit_task(session, self.profile.task())
        result = adapter.wait_for_completion(session, timeout=20)

        assert result.agent_version == "codex-cli 0.0.0-stub"

    def test_artifacts_are_recorded_with_paths_that_exist(self) -> None:
        adapter = self.profile.make_adapter()
        session = adapter.start_session(self.profile.make_config(), self.profile.workspace())
        adapter.submit_task(session, self.profile.task())
        adapter.wait_for_completion(session, timeout=20)
        result = adapter.close_session(session)

        assert result.artifacts
        for path in result.artifacts.values():
            assert Path(path).is_file(), path
