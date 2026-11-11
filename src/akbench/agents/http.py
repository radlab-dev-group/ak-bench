"""The API-class adapter (``http``, execution_type ``http``).

This is the reference implementation of the second agent class named in plan
6.5: an agent that lives behind an HTTP endpoint instead of a local process.
The protocol is AK-Bench's own — the four requests below are the contract an
agent server has to fulfil to be benchmarkable, and they are documented in
``docs/AGENT_ADAPTERS.md``. No vendor product is assumed to speak them; where
one does not, it needs its own adapter that translates this contract into
whatever it really exposes (plan 29.10: nothing is invented about a product).

THE PROTOCOL
    ``POST /tasks``
        Open a session and hand over the task. Request:
        ``{"task": str, "workspace": str | None, "parameters": dict}``.
        Response ``201``: ``{"session_id": str}``.
    ``GET /sessions/{id}``
        Liveness and state. Response ``200``:
        ``{"state": "pending"|"running"|"completed"|"failed"|"cancelled"|
          "infrastructure_error", "detail": str | None}``.
    ``POST /sessions/{id}/cancel``
        Ask the server to stop. Response ``200``; a server that cannot cancel
        answers ``405`` and the descriptor says so.
    ``GET /sessions/{id}/result``
        The outcome, in the universal shape of plan 6.3. Response ``200``:
        ``{"status": str, "final_message": str | None, "exit_code": int | None,
          "workspace_changes": [str], "observations": dict, "artifacts": dict,
          "token_usage": {"input_tokens": int, "output_tokens": int} | None}``.
    ``GET /version``
        Optional. Response ``200``: ``{"version": str}``.

WHAT THE ADAPTER PROMISES
    The workspace belongs to the server, so ``workspace_binding`` is
    ``partial``: the local workspace path is sent, and whether the agent works
    in it is the server's decision. Token usage and cost are ``unsupported``
    unless the server reports them, in which case they are passed through as
    reported and never filled in. A connection that fails, a ``5xx`` or a
    malformed answer is an infrastructure error, never an agent failure (plan
    rule 11); a task the server itself failed is the agent's.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
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
from akbench.agents.errors import AgentConfigError, AgentError, SessionClosed

ADAPTER_ID = "http"

#: Statuses a server may report, and what they mean here. Anything else is a
#: protocol violation, not a status.
SERVER_STATES: dict[str, AgentStatus] = {
    "pending": AgentStatus.PENDING,
    "running": AgentStatus.RUNNING,
    "completed": AgentStatus.COMPLETED,
    "failed": AgentStatus.FAILED,
    "timeout": AgentStatus.TIMED_OUT,
    "cancelled": AgentStatus.CANCELLED,
    "infrastructure_error": AgentStatus.INFRASTRUCTURE_ERROR,
}

#: How often the adapter asks for state while waiting, in seconds.
DEFAULT_POLL_INTERVAL = 0.05

#: The request timeout for one HTTP call, in seconds. The run budget is
#: separate and usually far larger.
DEFAULT_REQUEST_TIMEOUT = 30.0

ARTIFACT_FILE = "http_exchange.json"


@dataclass
class _HttpRun:
    """Per-session bookkeeping: what the server said and when."""

    session_id: str | None = None
    status: AgentStatus = AgentStatus.PENDING
    detail: str | None = None
    task: str | None = None
    result: dict[str, Any] | None = None
    started_at: float | None = None
    finished_at: float | None = None
    exit_code: int | None = None
    cancelled: bool = False
    timed_out: bool = False
    version: str | None = None
    exchange: list[dict[str, Any]] = field(default_factory=list)


class HttpAdapter:
    """Talks the AK-Bench agent-server protocol over HTTP."""

    adapter_id = ADAPTER_ID

    def __init__(
        self,
        descriptor: Any = None,
        base_url: str | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
        report_version: bool = True,
        opener: Any = None,
    ) -> None:
        self.descriptor = descriptor
        self.base_url = (base_url or "").rstrip("/") or None
        self.poll_interval = poll_interval
        self.request_timeout = request_timeout
        self.report_version = report_version
        #: Tests replace this with a callable that answers without a socket.
        self._opener = opener
        self.calls: list[str] = []

    # ------------------------------------------------------------------ env

    def validate_environment(self, config: AgentConfig) -> None:
        self.calls.append("validate_environment")
        problems: list[str] = []
        if self._endpoint(config) is None:
            problems.append(
                "no endpoint: set agent config 'base_url' or a runtime binding with base_url"
            )
        credential = self._credential_env(config)
        if credential:
            import os

            if not os.environ.get(credential):
                problems.append(
                    f"environment variable {credential!r} required by the "
                    "runtime binding is not set"
                )
        if problems:
            raise AgentConfigError(f"{self.adapter_id} cannot run: " + "; ".join(problems))

    def detect_version(self) -> str | None:
        if not self.report_version:
            return None
        try:
            payload = self._request("GET", "/version")
        except AgentError:
            # /version is optional in the protocol: not knowing is a fact.
            return None
        if isinstance(payload, dict):
            version = payload.get("version")
            return str(version) if version else None
        return None

    # ---------------------------------------------------------------- session

    def start_session(self, config: AgentConfig, workspace: Path) -> AgentSession:
        self.calls.append("start_session")
        target = Path(workspace)
        if not target.is_dir():
            raise AgentError(f"workspace is not a directory: {target}")
        if config.artifacts_dir is not None:
            Path(config.artifacts_dir).mkdir(parents=True, exist_ok=True)
        run = _HttpRun(version=self.detect_version())
        session = AgentSession(
            adapter_id=self.adapter_id,
            agent_id=config.agent_id,
            workspace=target,
            state={"run": run, "config": config},
        )
        return session

    def submit_task(self, session: AgentSession, task: str) -> None:
        self.calls.append("submit_task")
        run = self._run(session)
        if session.closed:
            raise SessionClosed("session is closed")
        if run.session_id is not None:
            raise AgentError("this session already has a task in flight")
        if not task.strip():
            raise AgentError("task text is empty")
        config: AgentConfig = session.state["config"]
        body = {
            "task": task,
            "workspace": str(session.workspace),
            "parameters": dict(config.parameters),
        }
        payload = self._request(
            "POST", "/tasks", body=body, config=config, run=run, where="submit_task"
        )
        session_id = payload.get("session_id") if isinstance(payload, dict) else None
        if not session_id:
            raise AgentError("agent server accepted the task without a session_id")
        run.session_id = str(session_id)
        run.task = task
        run.status = AgentStatus.RUNNING
        run.started_at = time.time()
        session.session_id = run.session_id

    def wait_for_completion(
        self,
        session: AgentSession,
        timeout: float | None = None,
    ) -> AgentResult:
        self.calls.append("wait_for_completion")
        run = self._run(session)
        if run.session_id is None:
            raise AgentError("no task has been submitted for this session")
        if run.status in TERMINAL:
            return self._result(session)

        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            status = self.get_status(session)
            if status in TERMINAL:
                break
            if run.cancelled:
                run.status = AgentStatus.CANCELLED
                break
            if deadline is not None and time.monotonic() >= deadline:
                run.timed_out = True
                self.cancel(session)
                run.status = AgentStatus.TIMED_OUT
                break
            if self.poll_interval:
                time.sleep(self.poll_interval)

        run.finished_at = time.time()
        if run.status is AgentStatus.COMPLETED or run.status is AgentStatus.FAILED:
            self._fetch_result(session)
        return self._result(session)

    def get_status(self, session: AgentSession) -> AgentStatus:
        run = self._run(session)
        if run.session_id is None:
            return AgentStatus.PENDING
        if run.status in TERMINAL:
            return run.status
        config: AgentConfig = session.state["config"]
        payload = self._request(
            "GET",
            f"/sessions/{run.session_id}",
            config=config,
            run=run,
            where="get_status",
            allow_missing=True,
        )
        if payload is None:
            return run.status
        state = payload.get("state") if isinstance(payload, dict) else None
        mapped = SERVER_STATES.get(str(state)) if state is not None else None
        if mapped is None:
            raise AgentError(
                f"agent server reported unknown state {state!r}; "
                f"the protocol allows {sorted(SERVER_STATES)}"
            )
        run.status = mapped
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if detail:
            run.detail = str(detail)
        return run.status

    def collect_observations(self, session: AgentSession) -> dict[str, Any]:
        run = self._run(session)
        result = run.result or {}
        usage = result.get("token_usage")
        observations = result.get("observations") if isinstance(result, dict) else None
        merged: dict[str, Any] = dict(observations) if isinstance(observations, dict) else {}
        merged.setdefault("session_id", run.session_id)
        merged.setdefault("token_usage", usage if isinstance(usage, dict) else None)
        merged.setdefault("cost", None)
        merged.setdefault("tool_call_count", 0)
        merged.setdefault("observed_model", None)
        return merged

    def cancel(self, session: AgentSession) -> None:
        self.calls.append("cancel")
        run = self._run(session)
        if run.session_id is None:
            raise AgentError("no task has been submitted for this session")
        config: AgentConfig = session.state["config"]
        run.cancelled = True
        try:
            self._request(
                "POST",
                f"/sessions/{run.session_id}/cancel",
                body={},
                config=config,
                run=run,
                where="cancel",
                allow_missing=True,
            )
        except AgentError:
            # A server without a cancel endpoint is allowed by the protocol;
            # the run is still marked cancelled locally and reported so.
            run.detail = "agent server refused the cancellation"

    def close_session(self, session: AgentSession) -> AgentResult:
        self.calls.append("close_session")
        self._run(session)
        result = self._result(session)
        session.closed = True
        return result

    # ---------------------------------------------------------------- internal

    def _fetch_result(self, session: AgentSession) -> None:
        run = self._run(session)
        config: AgentConfig = session.state["config"]
        if run.result is not None:
            return
        payload = self._request(
            "GET",
            f"/sessions/{run.session_id}/result",
            config=config,
            run=run,
            where="get_result",
            allow_missing=True,
        )
        if isinstance(payload, dict):
            run.result = payload
            if payload.get("exit_code") is not None:
                run.exit_code = int(payload["exit_code"])
            elif run.status is AgentStatus.COMPLETED:
                run.exit_code = 0
            elif run.status is AgentStatus.FAILED:
                run.exit_code = 1

    def _result(self, session: AgentSession) -> AgentResult:
        run = self._run(session)
        payload = run.result or {}
        usage = None
        reported = payload.get("token_usage")
        if isinstance(reported, dict):
            usage = TokenUsage(
                input_tokens=_as_int(reported.get("input_tokens")),
                output_tokens=_as_int(reported.get("output_tokens")),
                total_tokens=_as_int(reported.get("total_tokens")),
            )
        changes = payload.get("workspace_changes")
        artifacts = dict(payload.get("artifacts") or {})
        if run.session_id is not None and session.state.get("config") is not None:
            artifacts.update(self._write_exchange(session))
        # A timeout is the agent being too slow; only a server that says so (or
    # a transport fault, which raises) is blamed on the environment.
        failure = FailureClass.INFRASTRUCTURE if (
            run.status is AgentStatus.INFRASTRUCTURE_ERROR
        ) else FailureClass.AGENT
        return AgentResult(
            agent_id=session.agent_id,
            agent_version=run.version,
            session_id=run.session_id,
            status=run.status,
            started_at=run.started_at or session.started_at,
            finished_at=run.finished_at or time.time(),
            final_message=payload.get("final_message") or run.detail,
            exit_code=run.exit_code,
            failure_class=failure,
            workspace_changes=[str(item) for item in changes] if isinstance(changes, list) else [],
            observations=self.collect_observations(session),
            artifacts=artifacts,
            usage=usage,
        )

    def _write_exchange(self, session: AgentSession) -> dict[str, str]:
        """Record the request/response pairs of the run as an artifact."""
        config: AgentConfig = session.state["config"]
        if config.artifacts_dir is None:
            return {}
        run = self._run(session)
        path = Path(config.artifacts_dir) / ARTIFACT_FILE
        path.write_text(
            json.dumps(run.exchange, indent=2, default=str) + "\n", encoding="utf-8"
        )
        return {"http_exchange": str(path)}

    def _endpoint(self, config: AgentConfig) -> str | None:
        declared = config.get("base_url")
        if declared:
            return str(declared).rstrip("/")
        if config.runtime is not None and config.runtime.base_url:
            return str(config.runtime.base_url).rstrip("/")
        return self.base_url

    def _credential_env(self, config: AgentConfig) -> str | None:
        declared = config.get("api_key_env")
        if declared:
            return str(declared)
        if config.runtime is not None and config.runtime.api_key_env:
            return config.runtime.api_key_env
        return None

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        config: AgentConfig | None = None,
        run: _HttpRun | None = None,
        where: str = "request",
        allow_missing: bool = False,
    ) -> dict[str, Any] | None:
        """One HTTP call. Transport and protocol faults are infrastructure."""
        endpoint = self._endpoint(config) if config is not None else self.base_url
        if endpoint is None:
            raise AgentConfigError(f"{self.adapter_id}: no endpoint configured")
        url = f"{endpoint}{path}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        credential = self._credential_env(config) if config is not None else None
        if credential:
            import os

            secret = os.environ.get(credential)
            if secret:
                headers["Authorization"] = f"Bearer {secret}"

        if self._opener is not None:
            try:
                status, raw = self._opener(method, url, data, headers)
            except Exception as exc:  # a failing transport is still infrastructure
                raise AgentError(f"agent server is unreachable at {url}: {exc}") from exc
            if allow_missing and int(status) in (404, 405):
                return None
            return self._decode(method, url, raw, int(status), where, run)

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.request_timeout) as response:
                return self._decode(
                    method, url, response.read(), int(response.status), where, run
                )
        except urllib.error.HTTPError as exc:
            if allow_missing and exc.code in (404, 405):
                return None
            return self._decode(method, url, exc.read(), int(exc.code), where, run)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AgentError(
                f"agent server is unreachable at {url}: {exc} "
                "(infrastructure error, not an agent failure)"
            ) from exc

    def _decode(
        self,
        method: str,
        url: str,
        raw: bytes | str | None,
        status: int,
        where: str,
        run: _HttpRun | None = None,
    ) -> dict[str, Any] | None:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else (raw or "")
        payload: Any = None
        if text.strip():
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise AgentError(
                    f"agent server answered {method} {url} with a malformed body: {exc}"
                ) from exc
        if status >= 500:
            raise AgentError(
                f"agent server failed {method} {url} with HTTP {status} "
                "(infrastructure error, not an agent failure)"
            )
        if status >= 400:
            raise AgentError(f"agent server rejected {method} {url} with HTTP {status}")
        self.calls.append(where)
        if payload is None:
            return {}
        if not isinstance(payload, dict):
            raise AgentError(f"agent server answered {method} {url} with a non-object body")
        if run is not None:
            run.exchange.append({"method": method, "url": url, "status": status, "body": payload})
        return payload

    def _run(self, session: AgentSession) -> _HttpRun:
        run = session.state.get("run")
        if not isinstance(run, _HttpRun):
            raise AgentError("session was not created by this adapter")
        return run


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


TERMINAL = {
    AgentStatus.COMPLETED,
    AgentStatus.FAILED,
    AgentStatus.TIMED_OUT,
    AgentStatus.CANCELLED,
    AgentStatus.INFRASTRUCTURE_ERROR,
}


@dataclass(frozen=True)
class HttpOptions:
    """Constructor defaults for the HTTP adapter."""

    base_url: str | None = None
    poll_interval: float = DEFAULT_POLL_INTERVAL
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    report_version: bool = True

    def as_kwargs(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "poll_interval": self.poll_interval,
            "request_timeout": self.request_timeout,
            "report_version": self.report_version,
        }


__all__ = [
    "ADAPTER_ID",
    "ARTIFACT_FILE",
    "DEFAULT_POLL_INTERVAL",
    "DEFAULT_REQUEST_TIMEOUT",
    "SERVER_STATES",
    "HttpAdapter",
    "HttpOptions",
]
