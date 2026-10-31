"""The run lifecycle: states, transitions and the record a run produces.

The state machine is the contract between the orchestrator and everything that
watches a run (the database, the CLI, a future scheduler). It is explicit and
small:

- forward states trace the plan's lifecycle (15): pending -> preparing ->
  validating -> configuring_runtime -> creating_workspace -> starting_agent ->
  executing -> collecting -> evaluating -> finalizing -> completed;
- terminal failure states capture *why* a run did not complete, so an
  infrastructure error is never read as an agent failure (rule 11).

Transitions are validated: a run cannot skip a step, and a terminal state
cannot be left again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from akbench.core.time import utc_now


class RunState(StrEnum):
    """The states of one run (plan section 15)."""

    PENDING = "pending"
    PREPARING = "preparing"
    VALIDATING = "validating"
    CONFIGURING_RUNTIME = "configuring_runtime"
    CREATING_WORKSPACE = "creating_workspace"
    STARTING_AGENT = "starting_agent"
    EXECUTING = "executing"
    COLLECTING = "collecting"
    EVALUATING = "evaluating"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    INFRASTRUCTURE_ERROR = "infrastructure_error"
    INVALID_CONFIGURATION = "invalid_configuration"
    EVALUATION_ERROR = "evaluation_error"


#: The only states a run may finish in.
TERMINAL_STATES = frozenset(
    {
        RunState.COMPLETED,
        RunState.FAILED,
        RunState.TIMEOUT,
        RunState.CANCELLED,
        RunState.INFRASTRUCTURE_ERROR,
        RunState.INVALID_CONFIGURATION,
        RunState.EVALUATION_ERROR,
    }
)

#: Forward states, in order. A transition must land on the next state or on a
#: terminal state.
FORWARD_CHAIN = (
    RunState.PENDING,
    RunState.PREPARING,
    RunState.VALIDATING,
    RunState.CONFIGURING_RUNTIME,
    RunState.CREATING_WORKSPACE,
    RunState.STARTING_AGENT,
    RunState.EXECUTING,
    RunState.COLLECTING,
    RunState.EVALUATING,
    RunState.FINALIZING,
    RunState.COMPLETED,
)


class InvalidTransition(Exception):
    """A lifecycle step that would skip a state or leave a terminal state."""


def transition_allowed(current: RunState, target: RunState) -> bool:
    """True when ``current -> target`` is a legal step of the machine."""
    if current is target:
        return False
    if current in TERMINAL_STATES:
        return False
    if target in TERMINAL_STATES:
        return True
    index = FORWARD_CHAIN.index(current)
    return FORWARD_CHAIN[index + 1] is target


@dataclass
class TransitionLog:
    """Every state change with its timestamp — the audit trail of one run."""

    events: list[dict[str, Any]] = field(default_factory=list)

    def record(self, state: RunState, note: str | None = None) -> None:
        event: dict[str, Any] = {
            "state": state.value,
            "at": utc_now().isoformat(),
        }
        if note:
            event["note"] = note
        self.events.append(event)

    def as_dict(self) -> list[dict[str, Any]]:
        return [dict(event) for event in self.events]


@dataclass
class RunContext:
    """Everything the orchestrator knows about one run, as it progresses.

    The orchestrator fills it in step by step; the CLI and (later) the
    scheduler read it. It is a plain dataclass on purpose: it can be logged,
    serialized or rendered without ceremony.
    """

    run_uid: str
    task_uid: str
    agent_id: str
    state: RunState = RunState.PENDING
    mode: str = "direct"
    runtime_id: str | None = None
    workspace_path: str | None = None
    session_id: str | None = None
    agent_version: str | None = None
    agent_status: str | None = None
    observations: dict[str, Any] | None = None
    evaluation: dict[str, Any] | None = None
    failure_class: str | None = None
    error_message: str | None = None
    exit_code: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    history: TransitionLog = field(default_factory=TransitionLog)

    def __post_init__(self) -> None:
        self.history.record(self.state, "run created")

    def transition(self, target: RunState, note: str | None = None) -> None:
        """Move to ``target``, refusing illegal steps.

        Refusing is deliberate: a silent skip would hide an orchestrator bug
        in the audit trail instead of surfacing it.
        """
        if not transition_allowed(self.state, target):
            raise InvalidTransition(f"{self.state.value} -> {target.value}")
        self.state = target
        self.history.record(target, note)

    def finish(self, target: RunState, note: str | None = None) -> None:
        """Move to a terminal state and stamp the end time."""
        self.transition(target, note)
        self.finished_at = utc_now()

    def as_record(self) -> dict[str, Any]:
        """A database-ready snapshot of the run."""
        return {
            "run_uid": self.run_uid,
            "task_uid": self.task_uid,
            "agent_id": self.agent_id,
            "mode": self.mode,
            "runtime_id": self.runtime_id,
            "workspace_path": self.workspace_path,
            "session_id": self.session_id,
            "agent_version": self.agent_version,
            "agent_status": self.agent_status,
            # What the agent itself reported (usage, tool calls, session): the
            # input to the efficiency and reliability metrics of plan section 18.
            "observations": self.observations,
            "evaluation": self.evaluation,
            "failure_class": self.failure_class,
            "error_message": self.error_message,
            "exit_code": self.exit_code,
            "state": self.state.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "history": self.history.as_dict(),
        }


@dataclass(frozen=True)
class RunOutcome:
    """The final verdict of an orchestrator run, for callers and tests.

    ``record`` is the complete :class:`RunContext` snapshot (workspace, session,
    evaluation, transition log), so a caller can persist or archive a run
    without reaching back into the orchestrator's internals.
    """

    run_uid: str
    state: RunState
    ok: bool
    detail: str | None = None
    record: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_uid": self.run_uid,
            "state": self.state.value,
            "ok": self.ok,
            "detail": self.detail,
        }
