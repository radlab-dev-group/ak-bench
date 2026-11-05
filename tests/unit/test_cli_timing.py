"""The elapsed-time feedback of ``experiment run`` (cli/timing.py).

A managed run waits minutes for its router instance with nothing else on
screen, which is the silence these helpers exist to break. They must stay
honest about it: the numbers come from the run's own transition log, and the
live line never appears where it would corrupt a pipe or a log.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from akbench.cli.timing import (
    StepClock,
    format_clock,
    format_duration,
    format_phases,
    phase_durations,
)
from akbench.orchestration.lifecycle import RunContext, RunState


def test_durations_read_as_a_person_reads_them() -> None:
    assert format_duration(4.16) == "4.2s"
    assert format_duration(42.4) == "42s"
    assert format_duration(131.0) == "2m11s"
    assert format_duration(3723.0) == "1h02m03s"
    # A run that never measured says so rather than showing a zero.
    assert format_duration(None) == "unknown"


def test_the_clock_counts_while_the_step_blocks() -> None:
    clock = StepClock("[3/48]")
    assert clock.elapsed >= 0.0
    clock.report_phase(RunState.CONFIGURING_RUNTIME.value)
    line = clock.line()
    assert line.startswith("[3/48] · ")
    assert line.endswith("configuring_runtime")


def test_the_clock_reports_a_wall_clock_time_not_a_monotonic_one() -> None:
    started = datetime(2026, 11, 4, 7, 30, 0, tzinfo=UTC)
    assert format_clock(started).count(":") == 2
    assert format_clock(None) == "unknown"


def _history(steps: list[tuple[str, float]]) -> list[dict[str, object]]:
    base = datetime(2026, 11, 4, 7, 0, 0, tzinfo=UTC)
    return [
        {"state": state, "at": (base + timedelta(seconds=offset)).isoformat()}
        for state, offset in steps
    ]


def test_phase_durations_read_the_runs_own_transition_log() -> None:
    record = {
        "history": _history(
            [
                ("pending", 0.0),
                ("configuring_runtime", 1.0),
                ("creating_workspace", 112.0),
                ("executing", 113.0),
                ("completed", 173.0),
            ]
        )
    }

    phases = phase_durations(record)

    # The interval after an event is the time spent in that event's state.
    assert phases == [
        ("pending", 1.0),
        ("configuring_runtime", 111.0),
        ("creating_workspace", 1.0),
        ("executing", 60.0),
    ]
    # The router start is named where a reader will look for it.
    assert "configuring_runtime 1m51s" in format_phases(phases)


def test_phase_durations_merge_repeats_and_drop_the_bookkeeping_jumps() -> None:
    """A note logged inside a state is not a phase, and neither is a millisecond."""
    record = {
        "history": _history(
            [
                ("configuring_runtime", 0.0),
                ("configuring_runtime", 20.0),  # a note, not a transition
                ("creating_workspace", 20.4),  # sub-second: the machine moving
                ("executing", 21.0),
                ("completed", 81.0),
            ]
        )
    }

    # The note extends the state it was logged in; the sub-second hop to the
    # next state stays a phase of its own.
    assert phase_durations(record) == [
        ("configuring_runtime", 20.4),
        ("creating_workspace", 0.6),
        ("executing", 60.0),
    ]


def test_phase_durations_survive_a_record_without_timestamps() -> None:
    assert phase_durations({}) == []
    assert phase_durations({"history": [{"state": "pending"}, {"state": "executing"}]}) == []


def test_the_run_reports_its_phase_to_an_observer() -> None:
    """The live line is honest only because the run says where it is."""
    seen: list[str] = []
    context = RunContext(
        run_uid="run-1",
        task_uid="wordcount-001@1.0.0",
        agent_id="codex",
        on_transition=seen.append,
    )

    context.transition(RunState.PREPARING, "loading")
    context.transition(RunState.VALIDATING, "checking")

    assert seen == ["preparing", "validating"]


def test_an_observed_transition_still_records_history() -> None:
    context = RunContext(
        run_uid="run-1",
        task_uid="wordcount-001@1.0.0",
        agent_id="codex",
        on_transition=lambda state: None,
    )

    context.transition(RunState.PREPARING, "loading")

    recorded = context.history.as_dict()
    assert [event["state"] for event in recorded][-1] == "preparing"
