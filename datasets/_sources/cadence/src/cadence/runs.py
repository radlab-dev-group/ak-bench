"""Runs and their states, with the transitions the engine is allowed to make.

A run is one occurrence of one task at one logical time: ``report@2026-11-02``
is a run, and no amount of retrying makes it a second one. Retrying raises the
attempt counter of the same run, which is what separates "this run failed twice"
from "two runs failed", and the difference is what a backfill has to get right.

The states::

    scheduled -> running -> succeeded
       ^            |
       |            v
       +-------- waiting  (a retry waiting for its backoff)
                    |
                    v
                  failed   (retries exhausted)

``scheduled -> waiting -> scheduled`` is the retry loop. ``failed`` is terminal:
a run that has exhausted its retries is only moved again by an explicit
``rerun``, which resets the attempt counter and is an operator's decision, not
the engine's. A transition outside the table raises
:class:`~cadence.errors.IllegalRunTransition` — a run that quietly refused to
move is worse than an exception, because the scheduler then believes a run is
somewhere it is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from cadence.errors import IllegalRunTransition


class RunState(StrEnum):
    SCHEDULED = "scheduled"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


#: what each state is allowed to become
TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.SCHEDULED: frozenset({RunState.RUNNING, RunState.FAILED}),
    RunState.RUNNING: frozenset(
        {RunState.SUCCEEDED, RunState.WAITING, RunState.FAILED, RunState.RUNNING}
    ),
    RunState.WAITING: frozenset({RunState.SCHEDULED, RunState.FAILED}),
    RunState.SUCCEEDED: frozenset({RunState.SCHEDULED}),
    RunState.FAILED: frozenset({RunState.SCHEDULED}),
}

#: states a run cannot leave except by an explicit rerun
TERMINAL = frozenset({RunState.SUCCEEDED, RunState.FAILED})


@dataclass
class Run:
    """One occurrence of a task, its attempt counter and the times it moved at."""

    run_id: str
    task: str
    logical_time: datetime
    attempt: int = 1
    state: RunState = RunState.SCHEDULED
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    next_attempt_at: datetime | None = None
    attempts: list[datetime] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.state, str):
            self.state = RunState(self.state)

    @property
    def active(self) -> bool:
        """Whether the run occupies one of the task's concurrent slots right now."""
        return self.state in (RunState.SCHEDULED, RunState.RUNNING)

    @property
    def open(self) -> bool:
        """Whether the run still has work left in it."""
        return self.state not in TERMINAL

    def moved_to(self, target: RunState) -> Run:
        if target not in TRANSITIONS[self.state]:
            raise IllegalRunTransition(f"{self.run_id}: {self.state.value} -> {target.value}")
        return self

    def duration_seconds(self) -> float | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()


def latest(runs: list[Run], task: str) -> Run | None:
    """The newest run of a task by logical time, ties broken by attempt."""
    candidates = [run for run in runs if run.task == task]
    if not candidates:
        return None
    return max(candidates, key=lambda run: (run.logical_time, run.attempt))


def latest_at_or_before(runs: list[Run], task: str, logical_time: datetime) -> Run | None:
    """The task's newest run that started no later than ``logical_time``."""
    candidates = [
        run for run in runs if run.task == task and run.logical_time <= logical_time
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda run: (run.logical_time, run.attempt))


def succeeded_at(runs: list[Run], task: str, logical_time: datetime) -> bool:
    """Whether the newest run of a task at or before ``logical_time`` succeeded."""
    newest = latest_at_or_before(runs, task, logical_time)
    return newest is not None and newest.state is RunState.SUCCEEDED


def blocked_before(runs: list[Run], task: str, logical_time: datetime) -> Run | None:
    """The task's own most recent run before ``logical_time`` that has not succeeded."""
    earlier = [
        run
        for run in runs
        if run.task == task
        and run.logical_time < logical_time
        and run.state is not RunState.SUCCEEDED
    ]
    if not earlier:
        return None
    return max(earlier, key=lambda run: (run.logical_time, run.attempt))
