"""Codex CLI adapter (``codex_cli``, execution_type ``process``).

Everything in this file is Codex knowledge and is deliberately confined here:
the engine only sees :class:`akbench.agents.contract.AgentAdapter`. The
behaviour encoded below is the recipe verified in phase 0
(``docs/AGENT_INTEGRATION.md``), not an assumption:

- one ``codex exec`` process per task, with a private ``CODEX_HOME`` per run,
  so nothing leaks between runs (that directory also holds the agent's own
  databases, which is what makes isolation meaningful);
- the model provider is configured inside that ``CODEX_HOME`` through
  ``env_key``, so the agent starts with no interactive login;
- ``--json`` gives a flat event stream (``thread.started``,
  ``turn.completed``, ``turn.failed``, ``item.completed``, ``error``);
- the session rollout under ``CODEX_HOME/sessions`` is the stable source for
  cumulative token usage, tool calls and the model/sandbox actually applied.

Fields the CLI does not report stay ``None`` — cost in particular is never
derived (see the descriptor: ``cost_usage: unsupported``).
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from akbench.agents.contract import (
    AgentConfig,
    AgentResult,
    AgentSession,
    AgentStatus,
    FailureClass,
    RuntimeBinding,
    TokenUsage,
)
from akbench.agents.errors import AgentConfigError, AgentError, SessionClosed
from akbench.descriptors.agent import AgentDescriptor

ADAPTER_ID = "codex_cli"

#: Markers that mean "the environment failed", not "the agent failed" (plan
#: rule 11). Deliberately conservative: a hit moves a failure from ``failed``
#: to ``infrastructure_error`` so the run is not counted against the agent.
INFRA_ERROR_MARKERS: tuple[str, ...] = (
    "connection refused",
    "connection reset",
    "connection aborted",
    "name resolution",
    "temporary failure in name resolution",
    "timed out",
    "temporarily unavailable",
    "rate limit",
    "502",
    "503",
    "504",
    "429",
)

STREAM_FILE = "agent_stdout.jsonl"
STDERR_FILE = "agent_stderr.log"
LAST_MESSAGE_FILE = "last_message.txt"
TRACE_FILE = "agent_trace.jsonl"
TOOL_CALLS_FILE = "tool_calls.jsonl"


@dataclass(frozen=True)
class CodexOptions:
    """How this adapter invokes the CLI. Values here are integration facts."""

    binary: str = "codex"
    #: Codex speaks the Responses wire protocol against a router (phase 0).
    wire_api: str = "responses"
    provider_name: str = "akbench"
    #: Cancel escalation windows, in seconds.
    interrupt_grace: float = 10.0
    terminate_grace: float = 5.0
    extra_args: tuple[str, ...] = ()


@dataclass
class _RunState:
    """Mutable per-session state owned by the adapter."""

    home: Path | None = None
    artifacts: Path | None = None
    env: dict[str, str] = field(default_factory=dict)
    command: list[str] = field(default_factory=list)
    process: subprocess.Popen | None = None
    readers: list[threading.Thread] = field(default_factory=list)
    task: str | None = None
    submitted_at: float | None = None
    finished_at: float | None = None
    exit_code: int | None = None
    timed_out: bool = False
    cancelled: bool = False
    status: AgentStatus = AgentStatus.PENDING
    version: str | None = None
    result: AgentResult | None = None


class CodexAdapter:
    """Drives ``codex exec`` as one isolated process per benchmark run."""

    adapter_id = ADAPTER_ID

    def __init__(
        self,
        descriptor: AgentDescriptor | None = None,
        options: CodexOptions | None = None,
    ) -> None:
        self.descriptor = descriptor
        self.options = options or CodexOptions()
        self.binary = self.options.binary

    # ------------------------------------------------------------------ env

    def validate_environment(self, config: AgentConfig) -> None:
        """Check the host can actually start this agent, before any workspace work.

        Reports every problem in one message: a partial list would send the
        user hunting for the next missing piece.
        """
        problems: list[str] = []

        if shutil.which(self.binary) is None:
            problems.append(f"agent binary {self.binary!r} is not on PATH")

        binding = config.runtime
        if binding is not None:
            if not binding.base_url:
                problems.append("runtime binding has no base_url")
            if binding.api_key_env and not os.environ.get(binding.api_key_env):
                problems.append(
                    f"environment variable {binding.api_key_env!r} required by the "
                    "runtime binding is not set"
                )

        if problems:
            raise AgentConfigError(
                f"{self.adapter_id} cannot run: " + "; ".join(problems),
            )

    def detect_version(self) -> str | None:
        """Run the version command declared by the descriptor, if any."""
        command = None
        if self.descriptor is not None and self.descriptor.agent.version_detection:
            command = self.descriptor.agent.version_detection[0]
        argv = shlex.split(command) if command else [self.binary, "--version"]
        # The descriptor names the shipped binary; this adapter may point at a
        # different executable (a wrapper, or a test stub), so argv[0] follows it.
        argv[0] = self.binary
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        text = (completed.stdout or completed.stderr or "").strip()
        return text.splitlines()[0] if text else None

    # -------------------------------------------------------------- session

    def start_session(self, config: AgentConfig, workspace: Path) -> AgentSession:
        """Create a private ``CODEX_HOME`` and bind the run to ``workspace``.

        No process is started yet: ``codex exec`` takes the task text as an
        argument, so the process belongs to :meth:`submit_task`.
        """
        if config.artifacts_dir is None:
            raise AgentConfigError(
                f"{self.adapter_id} needs AgentConfig.artifacts_dir to store the "
                "agent event stream, its home directory and the session rollout"
            )
        target = Path(workspace)
        if not target.is_dir():
            raise AgentConfigError(f"workspace is not a directory: {target}")

        artifacts = Path(config.artifacts_dir)
        artifacts.mkdir(parents=True, exist_ok=True)
        home = artifacts / "agent_home"
        if home.exists():
            shutil.rmtree(home)
        home.mkdir(parents=True)
        (home / "config.toml").write_text(
            self._agent_config(config),
            encoding="utf-8",
        )

        env = dict(os.environ)
        env["CODEX_HOME"] = str(home)
        if config.runtime is not None:
            env.update(config.runtime.env)

        state = _RunState(
            home=home,
            artifacts=artifacts,
            env=env,
            command=self._command(config, target),
            version=self.detect_version(),
        )
        return AgentSession(
            adapter_id=self.adapter_id,
            agent_id=config.agent_id,
            workspace=target,
            # The engine never reads this; it is the adapter's own scratch space.
            state={"run": state},
        )

    def submit_task(self, session: AgentSession, task: str) -> None:
        """Launch the agent process for ``task`` (one turn per process)."""
        state = self._state(session)
        if session.closed:
            raise SessionClosed("cannot submit a task to a closed session")
        if state.process is not None:
            raise AgentError(
                f"{self.adapter_id} runs one task per session: this session already "
                "submitted a task, start a new session for another one"
            )
        if not task.strip():
            raise AgentError("task text is empty")
        if session.workspace is None:
            raise AgentError("session has no workspace bound")

        stdout_path = state.artifacts / STREAM_FILE
        stderr_path = state.artifacts / STDERR_FILE
        last_message = state.artifacts / LAST_MESSAGE_FILE

        argv = list(state.command)
        argv += ["-o", str(last_message)]
        argv += [*self.options.extra_args, task]
        state.command = argv

        process = subprocess.Popen(
            argv,
            cwd=session.workspace,
            env=state.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
        )
        state.process = process
        state.submitted_at = time.time()
        state.status = AgentStatus.RUNNING

        # Both pipes must be drained concurrently: an agent that talks a lot on
        # stderr would otherwise fill the 64 KiB pipe buffer and deadlock.
        state.readers = [
            _drain(process.stdout, stdout_path),
            _drain(process.stderr, stderr_path),
        ]

    # ------------------------------------------------------------- lifecycle

    def get_status(self, session: AgentSession) -> AgentStatus:
        state = self._state(session)
        if state.status in (
            AgentStatus.COMPLETED,
            AgentStatus.FAILED,
            AgentStatus.TIMED_OUT,
            AgentStatus.CANCELLED,
            AgentStatus.INFRASTRUCTURE_ERROR,
        ):
            return state.status
        process = state.process
        if process is None:
            return AgentStatus.PENDING
        if process.poll() is None:
            return AgentStatus.RUNNING
        return state.status

    def wait_for_completion(
        self,
        session: AgentSession,
        timeout: float | None = None,
    ) -> AgentResult:
        """Wait for the process, escalating to a cancel when the deadline hits."""
        state = self._state(session)
        process = state.process
        if process is None:
            raise AgentError("no task has been submitted for this session")

        if state.submitted_at is None:  # pragma: no cover - set on submit
            state.submitted_at = time.time()
        deadline = None if timeout is None else state.submitted_at + timeout
        for reader in state.readers:
            remaining = None if deadline is None else max(0.0, deadline - time.time())
            reader.join(remaining)

        if process.poll() is None:
            if deadline is not None and time.time() >= deadline:
                state.timed_out = True
                self.cancel(session)
            else:
                remaining = None if deadline is None else max(0.0, deadline - time.time())
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    state.timed_out = True
                    self.cancel(session)

        state.exit_code = process.returncode
        state.finished_at = time.time()
        return self._build_result(session)

    def cancel(self, session: AgentSession) -> None:
        """Interrupt the agent, escalating SIGINT → SIGTERM → SIGKILL.

        The agent declares ``cancellation: partial``: there is no agent-level
        cancel API, only process signals, and Codex still writes a final
        message on SIGINT.
        """
        state = self._state(session)
        process = state.process
        if process is None or process.poll() is not None:
            state.cancelled = True
            return
        state.cancelled = True
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
            if process.poll() is not None:
                return
            try:
                process.send_signal(sig)
            except (OSError, ValueError):  # pragma: no cover - process already gone
                return
            grace = {
                signal.SIGINT: self.options.interrupt_grace,
                signal.SIGTERM: self.options.terminate_grace,
                signal.SIGKILL: 5.0,
            }[sig]
            try:
                process.wait(timeout=grace)
                return
            except subprocess.TimeoutExpired:
                continue

    def close_session(self, session: AgentSession) -> AgentResult:
        """Reap the process and return the final normalized result."""
        state = self._state(session)
        process = state.process
        if process is not None and process.poll() is None:
            self.cancel(session)
        for reader in state.readers:
            reader.join(5.0)
        result = self._build_result(session)
        session.closed = True
        state.status = result.status
        return result

    # ---------------------------------------------------------- observations

    def collect_observations(self, session: AgentSession) -> dict[str, Any]:
        """Parse the event stream and, when present, the session rollout."""
        state = self._state(session)
        if state.artifacts is None:
            return {}

        stream = _parse_stream(state.artifacts / STREAM_FILE)
        rollout = _newest_rollout(state.home) if state.home else None
        observed = _read_rollout(rollout) if rollout else {}

        usage = _usage(stream.get("turn_usage"))
        cumulative = observed.get("cumulative_usage")
        if cumulative:
            usage = _usage(cumulative)

        tool_calls = observed.get("tool_names") or {}
        if not tool_calls:
            tool_calls = _tool_names(stream.get("items") or [])
        tool_call_count = observed.get("tool_call_count")
        if not tool_call_count:
            tool_call_count = sum(tool_calls.values())

        return {
            "session_id": stream.get("session_id"),
            "token_usage": usage.as_dict() if usage else None,
            "token_usage_source": (
                "rollout" if cumulative else ("event_stream" if usage else "unavailable")
            ),
            "tool_call_count": tool_call_count,
            "tool_names": tool_calls,
            "tool_trace_source": "rollout" if observed.get("tool_call_count") else "event_stream",
            "observed_model": observed.get("observed_model"),
            "observed_provider": observed.get("observed_provider"),
            "observed_sandbox": observed.get("observed_sandbox"),
            "observed_cwd": observed.get("observed_cwd"),
            "agent_version_observed": observed.get("cli_version"),
            "stream_error": stream.get("stream_error"),
            "turn_failed": stream.get("turn_failed"),
            "cost": None,  # Codex exposes no cost field: never guessed
            "rollout_available": rollout is not None,
        }

    # --------------------------------------------------------------- private

    def _state(self, session: AgentSession) -> _RunState:
        run = session.state.get("run")
        if not isinstance(run, _RunState):
            raise AgentError("session was not created by this adapter")
        return run

    def _agent_config(self, config: AgentConfig) -> str:
        """Render the agent's own ``config.toml`` for this run's home.

        Only declared, controllable parameters are written; anything else keeps
        the agent's default, which the run record then reports as unknown
        rather than assumed.
        """
        binding: RuntimeBinding | None = config.runtime
        lines = ["# Generated by AK-Bench for one isolated agent run."]
        model = config.get("model")
        if model:
            lines.append(f"model = {_toml_value(str(model))}")
        if binding is not None and binding.base_url:
            provider_id = _provider_id(binding.runtime_id or self.options.provider_name)
            lines.append(f"model_provider = {_toml_value(provider_id)}")
        lines.append(f"sandbox_mode = {_toml_value(str(config.get('sandbox_mode', 'read-only')))}")
        lines.append(
            f"approval_policy = {_toml_value(str(config.get('approval_policy', 'never')))}"
        )
        if binding is not None and binding.base_url:
            provider_id = _provider_id(binding.runtime_id or self.options.provider_name)
            lines.append("")
            lines.append(f"[model_providers.{provider_id}]")
            lines.append(f"name = {_toml_value(self.options.provider_name)}")
            lines.append(f"base_url = {_toml_value(f'{binding.base_url.rstrip("/")}/v1')}")
            lines.append(f"wire_api = {_toml_value(self.options.wire_api)}")
            if binding.api_key_env:
                lines.append(f"env_key = {_toml_value(binding.api_key_env)}")
        lines.append("")
        return "\n".join(lines)

    def _command(self, config: AgentConfig, workspace: Path) -> list[str]:
        argv = [self.binary, "exec", "--json", "--cd", str(workspace)]
        sandbox = config.get("sandbox_mode")
        if sandbox:
            argv += ["-s", str(sandbox)]
        approval = config.get("approval_policy")
        if approval:
            argv += ["-c", f'approval_policy="{approval}"']
        model = config.get("model")
        if model:
            argv += ["-m", str(model)]
        argv += ["--color", "never"]
        return argv

    def _build_result(self, session: AgentSession) -> AgentResult:
        state = self._state(session)
        observations = self.collect_observations(session)
        stderr_text = ""
        if state.artifacts is not None:
            stderr_path = state.artifacts / STDERR_FILE
            if stderr_path.is_file():
                stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")

        status, failure_class = self._classify(state, observations, stderr_text)
        state.status = status

        artifacts: dict[str, str] = {}
        if state.artifacts is not None:
            for key, name in (
                ("event_stream", STREAM_FILE),
                ("stderr", STDERR_FILE),
                ("last_message", LAST_MESSAGE_FILE),
            ):
                path = state.artifacts / name
                if path.is_file():
                    artifacts[key] = str(path)
            rollout = _newest_rollout(state.home) if state.home else None
            if rollout is not None:
                trace = state.artifacts / TRACE_FILE
                if not trace.exists():
                    shutil.copy2(rollout, trace)
                artifacts["session_rollout"] = str(trace)
                self._write_tool_calls(state.artifacts / TOOL_CALLS_FILE, observations)
                artifacts["tool_calls"] = str(state.artifacts / TOOL_CALLS_FILE)

        return AgentResult(
            agent_id=session.agent_id,
            agent_version=state.version or observations.get("agent_version_observed"),
            session_id=observations.get("session_id"),
            status=status,
            started_at=state.submitted_at or session.started_at,
            finished_at=state.finished_at or time.time(),
            final_message=self._final_message(state, observations),
            exit_code=state.exit_code,
            failure_class=failure_class,
            observations=observations,
            artifacts=artifacts,
            usage=_usage_from(observations.get("token_usage")),
        )

    def _final_message(self, state: _RunState, observations: dict[str, Any]) -> str | None:
        if state.artifacts is None:
            return None
        path = state.artifacts / LAST_MESSAGE_FILE
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                return text
        for item in reversed(_parse_stream(state.artifacts / STREAM_FILE).get("items") or []):
            if item.get("type") == "agent_message" and item.get("text"):
                return str(item["text"])
        return None

    def _classify(
        self,
        state: _RunState,
        observations: dict[str, Any],
        stderr_text: str,
    ) -> tuple[AgentStatus, FailureClass]:
        """Split infrastructure failures from agent failures (plan rule 11)."""
        low = stderr_text.lower()
        infra_hit = [marker for marker in INFRA_ERROR_MARKERS if marker in low]
        stream_failed = bool(observations.get("stream_error") or observations.get("turn_failed"))

        if state.cancelled and not state.timed_out:
            return AgentStatus.CANCELLED, FailureClass.AGENT
        if state.timed_out:
            return AgentStatus.TIMED_OUT, FailureClass.AGENT
        if stream_failed:
            if infra_hit:
                return AgentStatus.INFRASTRUCTURE_ERROR, FailureClass.INFRASTRUCTURE
            return AgentStatus.FAILED, FailureClass.AGENT
        if state.exit_code not in (0, None):
            if infra_hit:
                return AgentStatus.INFRASTRUCTURE_ERROR, FailureClass.INFRASTRUCTURE
            return AgentStatus.FAILED, FailureClass.AGENT
        return AgentStatus.COMPLETED, FailureClass.AGENT

    def _write_tool_calls(self, path: Path, observations: dict[str, Any]) -> None:
        names = observations.get("tool_names") or {}
        with open(path, "w", encoding="utf-8") as handle:
            for name, count in sorted(names.items()):
                handle.write(json.dumps({"name": name, "count": count}) + "\n")


# --------------------------------------------------------------------- helpers


def _provider_id(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value)


def _toml_value(value: Any) -> str:
    """Render a TOML scalar. JSON syntax is valid TOML for these types."""
    return json.dumps(value)


def _drain(pipe: Any, path: Path) -> threading.Thread:
    """Copy a pipe to a file in the background, so the buffer never fills."""

    def pump() -> None:
        if pipe is None:
            return
        with open(path, "w", encoding="utf-8", errors="replace") as handle:
            for line in pipe:
                handle.write(line)
        pipe.close()

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    return thread


def _parse_stream(path: Path) -> dict[str, Any]:
    """Parse the flat ``codex exec --json`` event stream."""
    parsed: dict[str, Any] = {
        "session_id": None,
        "turn_usage": None,
        "final_message": None,
        "stream_error": None,
        "turn_failed": None,
        "items": [],
    }
    if not path.is_file():
        return parsed

    usage: dict[str, int] = {}
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            if kind == "thread.started":
                parsed["session_id"] = event.get("thread_id")
            elif kind == "turn.completed":
                for key, value in (event.get("usage") or {}).items():
                    if isinstance(value, int):
                        usage[key] = usage.get(key, 0) + value
            elif kind == "turn.failed":
                parsed["turn_failed"] = event.get("error")
            elif kind == "error":
                parsed["stream_error"] = event.get("message")
            elif kind == "item.completed":
                item = event.get("item") or {}
                parsed["items"].append(item)
                if item.get("type") == "agent_message" and item.get("text"):
                    parsed["final_message"] = item["text"]
    if usage:
        parsed["turn_usage"] = usage
    return parsed


def _newest_rollout(home: Path | None) -> Path | None:
    if home is None:
        return None
    sessions = home / "sessions"
    if not sessions.is_dir():
        return None
    rollouts = sorted(
        (path for path in sessions.rglob("rollout-*.jsonl") if path.is_file()),
        key=lambda path: (path.stat().st_mtime, path.name),
    )
    return rollouts[-1] if rollouts else None


def _read_rollout(rollout: Path) -> dict[str, Any]:
    """Read cumulative usage, tool calls and the effective model/sandbox.

    The rollout is the agent's own session record, which is why it is the only
    trustworthy place for what was *actually* applied (``docs/AGENT_INTEGRATION.md``).
    """
    info: dict[str, Any] = {
        "cumulative_usage": None,
        "observed_model": None,
        "observed_provider": None,
        "observed_sandbox": None,
        "observed_cwd": None,
        "cli_version": None,
        "tool_call_count": 0,
        "tool_names": {},
    }
    with open(rollout, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            kind = record.get("type")
            payload = record.get("payload")
            if not isinstance(payload, dict):
                payload = {}
            if kind == "session_meta":
                info["cli_version"] = payload.get("cli_version") or info["cli_version"]
                observed = payload.get("model_provider") or info["observed_provider"]
                info["observed_provider"] = observed
                info["observed_cwd"] = payload.get("cwd") or info["observed_cwd"]
                if payload.get("model"):
                    info["observed_model"] = payload["model"]
            elif kind == "turn_context":
                if payload.get("model"):
                    info["observed_model"] = payload["model"]
                policy = payload.get("sandbox_policy")
                if isinstance(policy, dict) and policy.get("type"):
                    info["observed_sandbox"] = policy["type"]
                info["observed_cwd"] = payload.get("cwd") or info["observed_cwd"]
            elif kind == "token_usage_record":
                thread_usage = payload.get("thread_token_usage")
                if isinstance(thread_usage, dict):
                    info["cumulative_usage"] = thread_usage
            elif kind == "response_item" and payload.get("type") == "function_call":
                name = payload.get("name") or "unknown"
                names: dict[str, int] = info["tool_names"]
                names[name] = names.get(name, 0) + 1
                info["tool_call_count"] += 1
    return info


def _tool_names(items: list[dict[str, Any]]) -> dict[str, int]:
    names: dict[str, int] = {}
    for item in items:
        if item.get("type") in ("function_call", "command"):
            name = str(item.get("name") or item.get("type"))
            names[name] = names.get(name, 0) + 1
    return names


def _usage(raw: dict[str, Any] | None) -> TokenUsage | None:
    if not raw:
        return None
    return _usage_from(raw)


def _usage_from(raw: dict[str, Any] | None) -> TokenUsage | None:
    """Map a usage record onto the universal model, keeping unknowns ``None``."""
    if not raw:
        return None

    def pick(*keys: str) -> int | None:
        for key in keys:
            value = raw.get(key)
            if isinstance(value, int):
                return value
        return None

    return TokenUsage(
        input_tokens=pick("input_tokens", "prompt_tokens"),
        cached_input_tokens=pick("cached_input_tokens", "cached_tokens"),
        output_tokens=pick("output_tokens", "completion_tokens"),
        reasoning_output_tokens=pick("reasoning_output_tokens", "reasoning_tokens"),
        total_tokens=pick("total_tokens"),
    )
