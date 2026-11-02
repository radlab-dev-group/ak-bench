"""Pruning keeps the newest run of every task, because something waits on it."""

from datetime import UTC, datetime

from cadence.retention import keep_runs
from cadence.runs import Run, RunState


def _run(task, day):
    return Run(
        run_id=f"{task}@{day.isoformat()}", task=task, logical_time=day, state=RunState.SUCCEEDED
    )


def test_a_task_keeps_its_newest_run_even_when_it_is_old():
    old = _run("daily", datetime(2026, 1, 1, tzinfo=UTC))
    newer = _run("daily", datetime(2026, 6, 1, tzinfo=UTC))
    cutoff = datetime(2026, 3, 1, tzinfo=UTC)
    kept, dropped = keep_runs([old, newer], keep_per_task=1, newer_than=cutoff)
    assert kept == [newer]
    assert dropped == [old]


def test_everything_newer_than_the_cutoff_survives_whatever_the_task_keeps():
    old = _run("daily", datetime(2026, 1, 1, tzinfo=UTC))
    fresh = _run("daily", datetime(2026, 4, 1, tzinfo=UTC))
    cutoff = datetime(2026, 2, 1, tzinfo=UTC)
    kept, dropped = keep_runs([old, fresh], keep_per_task=1, newer_than=cutoff)
    assert kept == [fresh]
    assert dropped == [old]
