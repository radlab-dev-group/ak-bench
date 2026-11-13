"""Filling in the past. The rules are this docstring; writing them is the task.

``plan_catch_up(dag, history, *, start, end, max_runs_per_task=None)`` decides
which occurrences of a DAG inside a closed window still have to run, and in
which order, and returns a :class:`CatchUpPlan`. It is a pure function: the DAG
and the history are read and never modified, the clock is not consulted, and
calling it twice with the same arguments returns the same plan.

What an occurrence is
    For every task, the occurrences of its schedule inside ``[start, end)`` —
    start inclusive, end exclusive, as everywhere else in this package. An
    occurrence the time zone skipped does not exist and is never planned.

When an occurrence is already taken care of
    Look in ``history`` for a run of that task **at that exact logical time**:

    * ``succeeded`` — satisfied, nothing to plan;
    * ``scheduled``, ``running`` or ``waiting`` — already in flight, nothing to
      plan (re-planning it would double-run work somebody is doing);
    * ``failed`` — the occurrence is planned again. A failed run is an exhausted
      retry budget, not a result: the operator asked for the window and did not
      get it.

    A task with no run at that instant at all is simply missing, and is planned.

When an occurrence cannot be planned yet
    A plan must be a sequence the scheduler could actually execute, so an
    occurrence is placed only when everything it waits for is in place:

    An occurrence is **settled** when ``history`` holds a run of that task at
    that exact logical time that is not ``failed``, or when this plan already
    places it. A dependency is met when the task it waits for is settled at the
    same logical time:

    * each task in ``depends_on`` must be settled at **that same logical time**,
      either from ``history`` or from an earlier entry of this plan;
    * if the task ``depends_on_past``, its own previous occurrence inside the
      window must be settled. The planner does not reach before the window it
      was given, so the first occurrence of a task in the window carries no
      past wait;
    * when a wait cannot be met, the occurrence is **skipped** with the reason
      ``"waiting on <task>"``, naming the first dependency — in the order the
      task declares them — that is not settled. A ``depends_on_past`` wait that
      cannot be met reads as ``"waiting on <own task>"``.

    Skipping propagates: if an occurrence is skipped, nothing downstream of it —
    in the same task's past chain or in a dependent task — can be planned either,
    and each of those carries the same kind of reason.

Ordering
    Oldest logical time first. Within one logical time the plan is ordered by
    **dependency depth**, then by name:

    * a task whose waits at that time are all met from ``history`` — nothing
      left for this plan to place — is at depth 0;
    * any other task is at depth one more than the deepest task it waits for at
      that time, counting both ``depends_on`` and its own previous occurrence in
      the window;
    * tasks at the same depth are ordered by name.

    The depth is the whole rule, and it is deliberately not "whichever ready
    task comes first alphabetically": with tasks ``root``, ``middle`` and
    ``leaf`` chained and an unrelated ``solo``, the plan at one logical time is
    ``root, solo, middle, leaf`` — ``middle`` is deeper than ``solo`` even
    though its name sorts first among the tasks still waiting. A plan is
    therefore a valid topological order of the window, and applying it top-down
    never starts a run whose dependency is not already satisfied.

Limiting
    ``max_runs_per_task`` caps how many runs are planned for a single task. The
    cap is applied to the ordered plan, so it is always the oldest work that is
    kept and the newest that is skipped, and an occurrence skipped by the cap
    carries the reason ``"limit"``. The cap never reorders what it keeps.

The result
    :class:`CatchUpPlan` holds ``runs`` (the planned work, in the order given
    above) and ``skipped`` (every occurrence not planned, each with its reason,
    in the same order). An occurrence already settled by ``history`` belongs to
    neither list; every other occurrence in the window is in exactly one of
    them, and the two never name the same occurrence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from cadence.dag import Dag
from cadence.runs import Run


@dataclass(frozen=True)
class PlannedRun:
    """One occurrence the catch-up wants to run."""

    task: str
    logical_time: datetime
    depends_on: tuple[str, ...] = ()
    depends_on_past: bool = False


@dataclass(frozen=True)
class SkippedRun:
    """One occurrence the catch-up will not run, and why."""

    task: str
    logical_time: datetime
    reason: str


@dataclass
class CatchUpPlan:
    """The whole decision: what to run, what not to, and in which order."""

    runs: list[PlannedRun] = field(default_factory=list)
    skipped: list[SkippedRun] = field(default_factory=list)

    def tasks(self) -> list[str]:
        return sorted({run.task for run in self.runs})

    def for_task(self, task: str) -> list[PlannedRun]:
        return [run for run in self.runs if run.task == task]

    def reasons(self) -> dict[tuple[str, datetime], str]:
        return {(item.task, item.logical_time): item.reason for item in self.skipped}


def plan_catch_up(
    dag: Dag,
    history: list[Run],
    *,
    start: datetime,
    end: datetime,
    max_runs_per_task: int | None = None,
) -> CatchUpPlan:
    """Plan the runs that still have to happen between ``start`` and ``end``."""
    raise NotImplementedError("plan_catch_up is specified in this module and not yet written")
