"""The shared adapter contract suite (plan section 6.8).

Every adapter must pass this suite before an experiment may be recorded as
``valid``. Each test names the contract point it proves, so a failure says
which promise an adapter breaks rather than just "something went wrong".

A suite subclass provides two fixtures:

``profile``
    a factory for the adapter under test plus the declared behaviour flags,
    because the contract allows adapters to be weaker than each other.
``adapter``
    a fresh adapter instance for one test.

Adapters that cannot support an operation declare it through the profile, which
skips that test with the reason — never by quietly passing a fake assertion.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import pytest

from akbench.agents.contract import (
    AgentConfig,
    AgentResult,
    AgentSession,
    AgentStatus,
    FailureClass,
)
from akbench.agents.errors import AgentError

#: The exact JSON shape promised in plan section 6.3.
UNIVERSAL_RESULT_KEYS = {
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


class AdapterProfile(Protocol):
    """How a suite tells the shared tests what the adapter claims to do."""

    tmp_path: Path

    # --- capabilities the suite may rely on -------------------------------
    one_shot: bool
    supports_cancellation: bool
    requires_runtime_binding: bool
    reports_infrastructure_separately: bool
    reports_usage: bool
    reports_version: bool

    def make_adapter(self) -> Any: ...
    def make_config(self, **overrides: Any) -> AgentConfig: ...
    def workspace(self) -> Path: ...
    def task(self) -> str: ...
    def task_was_delivered(self, adapter: Any, session: AgentSession, task: str) -> bool: ...
    def hang_config(self) -> AgentConfig: ...


class AgentContractSuite:
    """Contract points every adapter must satisfy."""

    profile: Any

    # ------------------------------------------------------------ configure

    def test_valid_configuration_is_accepted(self) -> None:
        """A configuration the descriptor declares must validate."""
        self.profile.make_adapter().validate_environment(self.profile.make_config())

    def test_missing_runtime_credential_is_reported(self) -> None:
        """An adapter bound to a runtime must refuse to start without its credential."""
        if not self.profile.requires_runtime_binding:
            pytest.skip("adapter does not bind to a runtime endpoint")
        from akbench.agents.contract import RuntimeBinding

        config = self.profile.make_config(
            runtime=RuntimeBinding(
                runtime_id="test-runtime",
                base_url="http://127.0.0.1:1/v1",
                api_key_env="AKBENCH_CONTRACT_TEST_ABSENT_KEY",
            )
        )
        with pytest.raises((AgentError, ValueError)) as excinfo:
            self.profile.make_adapter().validate_environment(config)
        assert "AKBENCH_CONTRACT_TEST_ABSENT_KEY" in str(excinfo.value)

    # ------------------------------------------------------------ workspace

    def test_start_session_binds_the_workspace(self) -> None:
        workspace = self.profile.workspace()
        adapter = self.profile.make_adapter()
        session = adapter.start_session(self.profile.make_config(), workspace)

        assert isinstance(session, AgentSession)
        assert session.workspace == workspace
        assert session.closed is False
        assert session.agent_id == self.profile.make_config().agent_id

    def test_absent_workspace_directory_is_rejected(self) -> None:
        adapter = self.profile.make_adapter()
        missing = self.profile.tmp_path / "does-not-exist"
        with pytest.raises((AgentError, ValueError)):
            adapter.start_session(self.profile.make_config(), missing)

    # ------------------------------------------------------------- submission

    def test_task_reaches_the_agent(self) -> None:
        adapter = self.profile.make_adapter()
        config = self.profile.make_config()
        session = adapter.start_session(config, self.profile.workspace())
        task = self.profile.task()

        adapter.submit_task(session, task)
        adapter.wait_for_completion(session, timeout=10)

        assert self.profile.task_was_delivered(adapter, session, task)

    def test_waiting_without_a_task_is_refused(self) -> None:
        adapter = self.profile.make_adapter()
        session = adapter.start_session(self.profile.make_config(), self.profile.workspace())
        with pytest.raises(AgentError):
            adapter.wait_for_completion(session, timeout=5)

    def test_empty_task_text_is_refused(self) -> None:
        adapter = self.profile.make_adapter()
        session = adapter.start_session(self.profile.make_config(), self.profile.workspace())
        with pytest.raises(AgentError):
            adapter.submit_task(session, "   ")

    def test_one_session_does_not_accept_a_second_task(self) -> None:
        """Where an agent is one-shot, the second submission must fail loudly."""
        if not self.profile.one_shot:
            pytest.skip("adapter supports several submissions per session")
        adapter = self.profile.make_adapter()
        session = adapter.start_session(self.profile.make_config(), self.profile.workspace())
        adapter.submit_task(session, self.profile.task())
        adapter.wait_for_completion(session, timeout=10)
        with pytest.raises(AgentError):
            adapter.submit_task(session, self.profile.task())

    # ------------------------------------------------------------ completion

    def test_completion_is_detected(self) -> None:
        adapter = self.profile.make_adapter()
        session = adapter.start_session(self.profile.make_config(), self.profile.workspace())
        adapter.submit_task(session, self.profile.task())

        result = adapter.wait_for_completion(session, timeout=30)

        assert isinstance(result, AgentResult)
        assert result.status is AgentStatus.COMPLETED
        assert result.failure_class is FailureClass.AGENT
        assert result.finished_at is not None
        assert result.duration_seconds is not None

    def test_failure_is_not_reported_as_success(self) -> None:
        if not hasattr(self.profile, "failing"):
            pytest.skip("profile does not model a failing run")
        adapter = self.profile.failing()
        session = adapter.start_session(self.profile.make_config(), self.profile.workspace())
        adapter.submit_task(session, self.profile.task())

        result = adapter.wait_for_completion(session, timeout=30)

        assert result.status is not AgentStatus.COMPLETED
        assert result.status in {
            AgentStatus.FAILED,
            AgentStatus.INFRASTRUCTURE_ERROR,
            AgentStatus.CANCELLED,
        }

    def test_infrastructure_failure_is_separated_from_agent_failure(self) -> None:
        """Plan rule 11: a network fault must never be scored as an agent failure."""
        if not self.profile.reports_infrastructure_separately:
            pytest.skip("adapter cannot distinguish infrastructure failures")
        adapter = self.profile.infrastructure_failure()
        session = adapter.start_session(self.profile.make_config(), self.profile.workspace())
        adapter.submit_task(session, self.profile.task())

        result = adapter.wait_for_completion(session, timeout=30)

        assert result.status is AgentStatus.INFRASTRUCTURE_ERROR
        assert result.failure_class is FailureClass.INFRASTRUCTURE

    # --------------------------------------------------------------- timeout

    def test_timeout_is_reported_as_timeout(self) -> None:
        adapter = self.profile.hanging()
        session = adapter.start_session(self.profile.make_config(), self.profile.workspace())
        adapter.submit_task(session, self.profile.task())

        result = adapter.wait_for_completion(session, timeout=0.2)

        assert result.status is AgentStatus.TIMED_OUT

    # ------------------------------------------------------------ cancellation

    def test_cancellation_stops_the_run(self) -> None:
        if not self.profile.supports_cancellation:
            pytest.skip("adapter declares cancellation as unsupported")
        adapter = self.profile.hanging()
        session = adapter.start_session(self.profile.make_config(), self.profile.workspace())
        adapter.submit_task(session, self.profile.task())

        adapter.cancel(session)
        result = adapter.wait_for_completion(session, timeout=30)

        assert result.status in {AgentStatus.CANCELLED, AgentStatus.TIMED_OUT}

    # ------------------------------------------------------------- lifecycle

    def test_status_uses_the_shared_vocabulary(self) -> None:
        adapter = self.profile.make_adapter()
        session = adapter.start_session(self.profile.make_config(), self.profile.workspace())

        assert adapter.get_status(session) in set(AgentStatus)

    def test_status_progresses_from_pending_to_terminal(self) -> None:
        adapter = self.profile.make_adapter()
        session = adapter.start_session(self.profile.make_config(), self.profile.workspace())
        assert adapter.get_status(session) is AgentStatus.PENDING

        adapter.submit_task(session, self.profile.task())
        adapter.wait_for_completion(session, timeout=30)
        result = adapter.close_session(session)

        assert result.status in set(AgentStatus)
        assert result.status is not AgentStatus.PENDING
        assert result.status is not AgentStatus.RUNNING

    def test_close_session_is_idempotent(self) -> None:
        adapter = self.profile.make_adapter()
        session = adapter.start_session(self.profile.make_config(), self.profile.workspace())
        adapter.submit_task(session, self.profile.task())
        adapter.wait_for_completion(session, timeout=30)

        first = adapter.close_session(session)
        second = adapter.close_session(session)

        assert session.closed is True
        assert first.status is second.status

    def test_operations_on_a_closed_session_are_refused(self) -> None:
        if not self.profile.one_shot:
            pytest.skip("adapter keeps accepting work after close")
        adapter = self.profile.make_adapter()
        session = adapter.start_session(self.profile.make_config(), self.profile.workspace())
        adapter.close_session(session)
        with pytest.raises(AgentError):
            adapter.submit_task(session, self.profile.task())

    # ----------------------------------------------------------- observations

    def test_observations_are_a_plain_dict(self) -> None:
        adapter = self.profile.make_adapter()
        session = adapter.start_session(self.profile.make_config(), self.profile.workspace())
        adapter.submit_task(session, self.profile.task())
        adapter.wait_for_completion(session, timeout=30)

        observations = adapter.collect_observations(session)

        assert isinstance(observations, dict)

    def test_result_matches_the_universal_shape(self) -> None:
        adapter = self.profile.make_adapter()
        session = adapter.start_session(self.profile.make_config(), self.profile.workspace())
        adapter.submit_task(session, self.profile.task())
        result = adapter.wait_for_completion(session, timeout=30)

        payload = result.as_dict()
        assert set(payload) >= UNIVERSAL_RESULT_KEYS
        assert payload["agent_id"] == session.agent_id
        assert payload["status"] in {status.value for status in AgentStatus}
        assert isinstance(payload["workspace_changes"], list)
        assert isinstance(payload["observations"], dict)
        assert isinstance(payload["artifacts"], dict)

    def test_unavailable_values_stay_none_instead_of_zero(self) -> None:
        """An adapter that knows nothing reports nothing, never a plausible 0."""
        adapter = self.profile.without_usage()
        session = adapter.start_session(self.profile.make_config(), self.profile.workspace())
        adapter.submit_task(session, self.profile.task())
        result = adapter.wait_for_completion(session, timeout=30)

        if result.usage is not None:
            assert any(
                value is None for value in result.usage.as_dict().values()
            ), "an adapter without usage data must not fill every token field"
        observations = adapter.collect_observations(session)
        if not self.profile.reports_version:
            assert result.agent_version is None
        assert observations.get("cost", None) is None

    def test_cost_is_never_invented(self) -> None:
        adapter = self.profile.make_adapter()
        session = adapter.start_session(self.profile.make_config(), self.profile.workspace())
        adapter.submit_task(session, self.profile.task())
        result = adapter.wait_for_completion(session, timeout=30)

        assert "cost" not in {key for key, value in result.observations.items() if value}
