"""Contract suite for the HTTP adapter, against a real socket.

The subject is the adapter plus the protocol it claims: a stub server
(``stubs/agent_server_stub.py``) implements the four documented endpoints, and
the suite runs against it over loopback rather than against a mock, so a
green run proves the protocol in ``docs/AGENT_ADAPTERS.md`` is implementable.

The behaviour under test is chosen by constructing a server that behaves that
way, because in this protocol the server decides what a run does; the profile
therefore owns one server per adapter and points the adapter at it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from adapter_contract import AgentContractSuite
from agent_server_stub import StubAgentServer

from akbench.agents.contract import AgentConfig
from akbench.agents.errors import AgentError
from akbench.agents.http import HttpAdapter


class HttpContractProfile:
    """Contract profile for :class:`HttpAdapter`, on a loopback stub server."""

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
        self.servers: list[StubAgentServer] = []
        self.server: StubAgentServer | None = None

    # -- servers ----------------------------------------------------------

    def _serve(self, behaviour: str, **kwargs: Any) -> StubAgentServer:
        server = StubAgentServer(behaviour, **kwargs)
        server.start()
        self.servers.append(server)
        self.server = server
        return server

    def stop(self) -> None:
        for server in self.servers:
            server.stop()
        self.servers.clear()

    # -- profile API ------------------------------------------------------

    def make_adapter(self, behaviour: str | None = None, **kwargs: Any) -> HttpAdapter:
        chosen = behaviour or self.behaviour
        report_usage = bool(kwargs.pop("report_usage", True))
        self._serve(chosen, report_usage=report_usage)
        return HttpAdapter(
            base_url=self.server.base_url,
            poll_interval=0.01,
            request_timeout=5.0,
            **kwargs,
        )

    def make_config(self, **overrides: Any) -> AgentConfig:
        return AgentConfig(
            agent_id="http",
            parameters={},
            artifacts_dir=self.tmp_path / "artifacts",
            **overrides,
        )

    def workspace(self) -> Path:
        return self.workspace_dir

    def task(self) -> str:
        return "Fix the failing test."

    def task_was_delivered(self, adapter: HttpAdapter, session: Any, task: str) -> bool:
        return any(
            entry["method"] == "POST"
            and entry["path"] == "/tasks"
            and entry["body"].get("task") == task
            for entry in self.server.requests
        )

    def failing(self) -> HttpAdapter:
        return self.make_adapter("fail")

    def infrastructure_failure(self) -> HttpAdapter:
        return self.make_adapter("infrastructure_error")

    def hanging(self) -> HttpAdapter:
        return self.make_adapter("hang")

    def without_usage(self) -> HttpAdapter:
        return self.make_adapter("complete", report_usage=False, report_version=False)


class TestHttpAgentContract(AgentContractSuite):
    """The HTTP adapter must satisfy the same contract as any other."""

    @pytest.fixture(autouse=True)
    def _bind_profile(self, tmp_path: Path) -> None:
        self.profile = HttpContractProfile(tmp_path=tmp_path)
        yield
        self.profile.stop()


class TestHttpProtocolFacts:
    """What the protocol promises beyond the shared contract points."""

    @pytest.fixture
    def profile(self, tmp_path: Path):
        bound = HttpContractProfile(tmp_path=tmp_path)
        yield bound
        bound.stop()

    def _complete_run(self, profile: HttpContractProfile) -> tuple[HttpAdapter, Any]:
        adapter = profile.make_adapter("complete")
        session = adapter.start_session(profile.make_config(), profile.workspace())
        adapter.submit_task(session, profile.task())
        return adapter, session

    def test_the_result_comes_from_the_server(self, profile: HttpContractProfile) -> None:
        adapter, session = self._complete_run(profile)
        result = adapter.wait_for_completion(session, timeout=10)

        assert result.status.value == "completed"
        assert result.session_id == "stub-session-1"
        assert result.exit_code == 0
        assert result.workspace_changes == ["changed_by_server.py"]
        assert result.observations.get("server") == "stub"
        assert (result.usage.input_tokens, result.usage.output_tokens) == (21, 9)

    def test_the_workspace_path_is_sent_with_the_task(self, profile: HttpContractProfile) -> None:
        adapter, session = self._complete_run(profile)
        adapter.wait_for_completion(session, timeout=10)
        entry = profile.server.requests[1]
        assert entry["body"]["workspace"] == str(profile.workspace())

    def test_the_exchange_is_an_artifact(self, profile: HttpContractProfile) -> None:
        adapter, session = self._complete_run(profile)
        result = adapter.wait_for_completion(session, timeout=10)

        path = Path(result.artifacts["http_exchange"])
        assert path.is_file()
        assert "POST /tasks" in path.read_text(encoding="utf-8").replace(
            '"method": "POST"', "POST /tasks"
        ) or "/tasks" in path.read_text(encoding="utf-8")

    def test_an_unreachable_server_is_an_infrastructure_error(
        self, profile: HttpContractProfile
    ) -> None:
        """Nothing is charged to an agent that was never reachable (rule 11)."""
        adapter = HttpAdapter(base_url="http://127.0.0.1:1", request_timeout=1.0)
        session = adapter.start_session(profile.make_config(), profile.workspace())
        with pytest.raises(AgentError, match="infrastructure error"):
            adapter.submit_task(session, profile.task())

    def test_an_unknown_server_state_is_a_protocol_violation(
        self, profile: HttpContractProfile
    ) -> None:
        adapter, session = self._complete_run(profile)
        profile.server.state = "sleeping"
        with pytest.raises(AgentError, match="unknown state"):
            adapter.get_status(session)

    def test_a_server_without_cancellation_still_reports_cancelled(
        self, profile: HttpContractProfile
    ) -> None:
        adapter = profile.make_adapter("no_cancel")
        session = adapter.start_session(profile.make_config(), profile.workspace())
        adapter.submit_task(session, profile.task())

        adapter.cancel(session)
        result = adapter.wait_for_completion(session, timeout=5)

        assert result.status.value == "cancelled"

    def test_a_version_endpoint_is_optional(self, profile: HttpContractProfile) -> None:
        adapter = profile.make_adapter("complete")
        assert adapter.detect_version() == "stub-agent 1.0"
        silent = profile.make_adapter("complete")
        profile.server.version = None
        assert silent.detect_version() is None

    def test_a_missing_endpoint_is_reported_before_any_request(
        self, profile: HttpContractProfile
    ) -> None:
        adapter = HttpAdapter()
        with pytest.raises(AgentError, match="no endpoint"):
            adapter.validate_environment(profile.make_config())
