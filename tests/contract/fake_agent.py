"""A reference adapter: the smallest thing that satisfies the contract.

It is not a real agent — it is proof that the contract can be implemented
without knowing anything about Codex, and the deterministic subject of the
shared contract suite. Its behaviour is scripted (``complete``, ``hang``,
``fail``, ``infrastructure_error``) and it never starts a process, so the
suite runs in milliseconds.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from akbench.agents.contract import (
    AgentConfig,
    AgentResult,
    AgentSession,
    AgentStatus,
    FailureClass,
    TokenUsage,
)
from akbench.agents.errors import AgentError, SessionClosed

BEHAVIOURS = ("complete", "hang", "fail", "infrastructure_error")

TERMINAL = {
    AgentStatus.COMPLETED,
    AgentStatus.FAILED,
    AgentStatus.TIMED_OUT,
    AgentStatus.CANCELLED,
    AgentStatus.INFRASTRUCTURE_ERROR,
}


@dataclass
class _FakeRun:
    workspace: Path
    artifacts: Path | None = None
    behaviour: str = "complete"
    report_usage: bool = True
    state: str = "idle"
    exit_code: int | None = None
    started_at: float | None = None
    finished_at: float | None = None
    cancelled: bool = False
    timed_out: bool = False
    status: AgentStatus = AgentStatus.PENDING
    task: str | None = None
    version: str | None = "fake-agent 1.0"


class FakeAdapter:
    """In-memory adapter used as the contract reference implementation."""

    adapter_id = "fake"

    def __init__(
        self,
        descriptor: Any = None,
        behaviour: str = "complete",
        report_usage: bool = True,
        report_version: bool = True,
    ) -> None:
        if behaviour not in BEHAVIOURS:
            raise ValueError(f"unknown behaviour {behaviour!r}, expected one of {BEHAVIOURS}")
        self.descriptor = descriptor
        self.behaviour = behaviour
        self.report_usage = report_usage
        self.report_version = report_version
        self.calls: list[str] = []

    def validate_environment(self, config: AgentConfig) -> None:
        self.calls.append("validate_environment")
        if config.runtime is not None and config.runtime.api_key_env:
            import os

            if not os.environ.get(config.runtime.api_key_env):
                raise AgentError(f"missing credential {config.runtime.api_key_env}")

    def start_session(self, config: AgentConfig, workspace: Path) -> AgentSession:
        self.calls.append("start_session")
        target = Path(workspace)
        if not target.is_dir():
            raise AgentError(f"workspace is not a directory: {target}")
        artifacts = config.artifacts_dir
        if artifacts is not None:
            Path(artifacts).mkdir(parents=True, exist_ok=True)
        run = _FakeRun(
            workspace=target,
            artifacts=Path(artifacts) if artifacts is not None else None,
            behaviour=self.behaviour,
            report_usage=self.report_usage,
            version="fake-agent 1.0" if self.report_version else None,
        )
        return AgentSession(
            adapter_id=self.adapter_id,
            agent_id=config.agent_id,
            workspace=target,
            state={"run": run},
        )

    def submit_task(self, session: AgentSession, task: str) -> None:
        self.calls.append("submit_task")
        run = self._run(session)
        if session.closed:
            raise SessionClosed("session is closed")
        if run.state != "idle":
            raise AgentError("this fake session already submitted a task")
        if not task.strip():
            raise AgentError("task text is empty")
        run.task = task
        run.state = "running"
        run.started_at = time.time()
        run.status = AgentStatus.RUNNING

    def wait_for_completion(
        self,
        session: AgentSession,
        timeout: float | None = None,
    ) -> AgentResult:
        self.calls.append("wait_for_completion")
        run = self._run(session)
        if run.state == "idle":
            raise AgentError("no task has been submitted for this session")
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if run.state != "running":
                break
            if deadline is not None and time.monotonic() >= deadline:
                run.timed_out = True
                self.cancel(session)
                break
            if run.behaviour == "hang":
                if deadline is None:
                    raise AgentError("fake agent is hanging and no timeout was given")
                time.sleep(0.01)
            else:
                break

        run.finished_at = time.time()
        if run.state == "running":
            run.state = "finished"
            run.status = AgentStatus.COMPLETED
        if run.timed_out:
            run.status = AgentStatus.TIMED_OUT
        elif run.cancelled:
            run.status = AgentStatus.CANCELLED
        elif run.behaviour == "fail":
            run.status, run.exit_code = AgentStatus.FAILED, 1
        elif run.behaviour == "infrastructure_error":
            run.status, run.exit_code = AgentStatus.INFRASTRUCTURE_ERROR, 1
        else:
            run.status, run.exit_code = AgentStatus.COMPLETED, 0
        return self._result(session)

    def get_status(self, session: AgentSession) -> AgentStatus:
        run = self._run(session)
        if run.state == "running":
            return AgentStatus.RUNNING
        if run.state == "idle":
            return AgentStatus.PENDING
        return run.status

    def collect_observations(self, session: AgentSession) -> dict[str, Any]:
        run = self._run(session)
        return {
            "session_id": "fake-session" if run.state != "idle" else None,
            "token_usage": ({"input_tokens": 11, "output_tokens": 7} if run.report_usage else None),
            "cost": None,
            "tool_call_count": 0,
            "observed_model": None,
        }

    def cancel(self, session: AgentSession) -> None:
        self.calls.append("cancel")
        run = self._run(session)
        run.cancelled = True
        if run.state == "running":
            run.state = "finished"

    def close_session(self, session: AgentSession) -> AgentResult:
        self.calls.append("close_session")
        run = self._run(session)
        result = self._result(session)
        session.closed = True
        run.state = "closed"
        return result

    def _run(self, session: AgentSession) -> _FakeRun:
        run = session.state.get("run")
        if not isinstance(run, _FakeRun):
            raise AgentError("session was not created by this adapter")
        return run

    def _result(self, session: AgentSession) -> AgentResult:
        run = self._run(session)
        observations = self.collect_observations(session)
        usage = None
        if run.report_usage:
            usage = TokenUsage(input_tokens=11, output_tokens=7, total_tokens=18)
        artifacts = {}
        if run.artifacts is not None:
            path = run.artifacts / "fake_log.txt"
            path.write_text(f"fake run of {run.task!r}\n", encoding="utf-8")
            artifacts["log"] = str(path)
        failure = FailureClass.AGENT
        if run.status is AgentStatus.INFRASTRUCTURE_ERROR:
            failure = FailureClass.INFRASTRUCTURE
        return AgentResult(
            agent_id=session.agent_id,
            agent_version=run.version,
            session_id=observations.get("session_id"),
            status=run.status,
            started_at=run.started_at or session.started_at,
            finished_at=run.finished_at or time.time(),
            final_message="done" if run.state != "idle" else None,
            exit_code=run.exit_code,
            failure_class=failure,
            workspace_changes=[],
            observations=observations,
            artifacts=artifacts,
            usage=usage,
        )


def fake_config(agent_id: str = "fake", **parameters: Any) -> AgentConfig:
    return AgentConfig(agent_id=agent_id, parameters=dict(parameters))


@dataclass
class FakeProfile:
    """Contract-suite profile for :class:`FakeAdapter`."""

    tmp_path: Path
    behaviour: str = "complete"
    report_usage: bool = True
    report_version: bool = True
    one_shot: bool = True
    supports_cancellation: bool = True
    requires_runtime_binding: bool = False
    reports_infrastructure_separately: bool = True

    def make_adapter(self) -> FakeAdapter:
        return FakeAdapter(
            behaviour=self.behaviour,
            report_usage=self.report_usage,
            report_version=self.report_version,
        )

    def make_config(self, artifacts: bool = True, **overrides: Any) -> AgentConfig:
        return AgentConfig(
            agent_id="fake",
            parameters=dict(overrides),
            artifacts_dir=self.tmp_path / "artifacts" if artifacts else None,
        )

    def workspace(self) -> Path:
        workspace = self.tmp_path / "workspace"
        workspace.mkdir(exist_ok=True)
        return workspace

    def task(self) -> str:
        return "Fix the failing test."


__all__ = ["FakeAdapter", "FakeProfile"]
