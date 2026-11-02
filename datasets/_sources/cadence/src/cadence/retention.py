"""How long the engine remembers, and what forgetting costs.

Runs are kept so that ``depends_on_past`` and ``depends_on`` can be answered,
so pruning history is not a cleanup detail: it changes what the scheduler
believes has already happened. Two rules follow from that and they are the whole
of this module.

``keep_runs(runs, *, keep_per_task, newer_than)``
    A run survives when it is at or after ``newer_than`` **or** it is among the
    ``keep_per_task`` newest runs of its own task. The second half is what keeps
    a daily task with one long-finished run from being erased to nothing: the
    newest run of every task is a dependency target, and dropping it makes the
    next scheduler believe the task has never run.

``summarise(runs)``
    Per-task counts of every state, oldest facts first, so a report can show
    what a pruning removed before and after.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from cadence.runs import Run, RunState


def keep_runs(
    runs: list[Run], *, keep_per_task: int, newer_than: datetime
) -> tuple[list[Run], list[Run]]:
    """Split runs into ``(kept, dropped)`` under the two rules above."""
    if keep_per_task < 1:
        raise ValueError(f"keep_per_task must be positive, got {keep_per_task}")
    kept: list[Run] = []
    dropped: list[Run] = []
    for task in sorted({run.task for run in runs}):
        owned = sorted(
            (run for run in runs if run.task == task),
            key=lambda run: (run.logical_time, run.attempt),
        )
        newest = {id(run) for run in owned[-keep_per_task:]}
        for run in owned:
            if run.logical_time >= newer_than or id(run) in newest:
                kept.append(run)
            else:
                dropped.append(run)
    return kept, dropped


def summarise(runs: list[Run]) -> dict[str, dict[str, int]]:
    """State counts per task, as a plain structure a report can print."""
    summary: dict[str, dict[str, int]] = {}
    for task in sorted({run.task for run in runs}):
        counts: Counter[str] = Counter(run.state.value for run in runs if run.task == task)
        summary[task] = {state.value: counts.get(state.value, 0) for state in RunState}
        summary[task]["total"] = sum(1 for run in runs if run.task == task)
    return summary
