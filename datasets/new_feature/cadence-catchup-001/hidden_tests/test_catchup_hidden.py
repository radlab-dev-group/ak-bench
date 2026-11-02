"""The catch-up contract, enforced on the plan the agent hands back.

The planner is specified rather than guessed at, so every rule in the module
docstring has a test here: the half-open window, what settles an occurrence,
the two dependencies and how a skip propagates through them, the cap, the
ordering, and the purity of the whole thing. A wrong reading shows up as a
wrong plan rather than as an exception.
"""

from datetime import UTC, datetime

import pytest
from cadence.catchup import CatchUpPlan, plan_catch_up
from cadence.dag import Dag, TaskSpec
from cadence.runs import Run, RunState
from cadence.schedule import Schedule


def at(day, hour=6):
    return datetime(2026, 11, day, hour, 0, tzinfo=UTC)


def a_run(task, moment, state=RunState.SUCCEEDED):
    return Run(run_id=f"{task}@{moment.isoformat()}", task=task, logical_time=moment, state=state)


def daily():
    return Schedule.parse("0 6 * * *", "UTC")


def planned(plan, task=None):
    runs = plan.runs if task is None else plan.for_task(task)
    return [(run.task, run.logical_time.day) for run in runs]


def dropped(plan, task=None):
    items = plan.skipped if task is None else [i for i in plan.skipped if i.task == task]
    return [(item.logical_time.day, item.reason) for item in items]


# ------------------------------------------------------------------ the window


def test_an_empty_history_plans_every_occurrence_of_the_window():
    dag = Dag("ops")
    dag.add(TaskSpec("job", daily()))
    plan = plan_catch_up(dag, [], start=at(2), end=at(6))
    assert planned(plan, "job") == [("job", 2), ("job", 3), ("job", 4), ("job", 5)]
    assert plan.skipped == []


def test_a_window_that_starts_after_it_ends_plans_nothing():
    dag = Dag("ops")
    dag.add(TaskSpec("job", daily()))
    plan = plan_catch_up(dag, [], start=at(3), end=at(3))
    assert plan.runs == [] and plan.skipped == []


def test_a_run_at_the_window_end_is_not_planned_but_one_at_the_start_is():
    dag = Dag("ops")
    dag.add(TaskSpec("job", daily()))
    plan = plan_catch_up(dag, [], start=at(3), end=at(5))
    assert planned(plan, "job") == [("job", 3), ("job", 4)]


def test_an_occurrence_the_time_zone_skipped_is_neither_planned_nor_skipped():
    """Warsaw, 29 March 2026, has no 02:30; the planner does not invent one."""
    dag = Dag("ops")
    dag.add(TaskSpec("nightly", Schedule.parse("30 2 * * *", "Europe/Warsaw")))
    plan = plan_catch_up(
        dag,
        [],
        start=datetime(2026, 3, 27, tzinfo=UTC),
        end=datetime(2026, 3, 31, tzinfo=UTC),
    )
    days = sorted(run.logical_time.astimezone(UTC).day for run in plan.for_task("nightly"))
    assert days == [27, 28, 30]
    assert plan.skipped == []


# ------------------------------------------------------------- what settles one


def test_a_succeeded_run_is_not_planned_again():
    dag = Dag("ops")
    dag.add(TaskSpec("job", daily()))
    plan = plan_catch_up(dag, [a_run("job", at(3))], start=at(2), end=at(6))
    assert planned(plan, "job") == [("job", 2), ("job", 4), ("job", 5)]


@pytest.mark.parametrize("state", [RunState.SCHEDULED, RunState.RUNNING, RunState.WAITING])
def test_a_run_still_in_flight_is_not_planned_again(state):
    """Re-planning work somebody is doing is the mistake that costs real money."""
    dag = Dag("ops")
    dag.add(TaskSpec("job", daily()))
    plan = plan_catch_up(dag, [a_run("job", at(3), state)], start=at(2), end=at(6))
    assert ("job", 3) not in planned(plan)


def test_a_failed_run_is_planned_again():
    """A failed run is an exhausted retry budget, not the result the operator asked for."""
    dag = Dag("ops")
    dag.add(TaskSpec("job", daily()))
    plan = plan_catch_up(dag, [a_run("job", at(3), RunState.FAILED)], start=at(2), end=at(6))
    assert planned(plan, "job") == [("job", 2), ("job", 3), ("job", 4), ("job", 5)]


def test_a_settled_run_of_another_task_does_not_settle_this_one():
    dag = Dag("ops")
    dag.add(TaskSpec("job", daily()))
    plan = plan_catch_up(dag, [a_run("other", at(3))], start=at(2), end=at(6))
    assert len(plan.for_task("job")) == 4


# ---------------------------------------------------------- depends_on, same time


def test_a_dependent_task_is_planned_after_what_it_waits_for_at_the_same_instant():
    dag = Dag("ops")
    dag.add(TaskSpec("report", daily(), depends_on=("extract",)), TaskSpec("extract", daily()))
    plan = plan_catch_up(dag, [], start=at(2), end=at(3))
    planned = [(run.task, run.logical_time.day) for run in plan.runs]
    assert planned == [("extract", 2), ("report", 2)]


def test_a_settled_upstream_settles_its_dependent_at_that_time():
    dag = Dag("ops")
    dag.add(TaskSpec("report", daily(), depends_on=("extract",)), TaskSpec("extract", daily()))
    plan = plan_catch_up(dag, [a_run("extract", at(3))], start=at(2), end=at(5))
    assert planned(plan, "extract") == [("extract", 2), ("extract", 4)]
    assert planned(plan, "report") == [("report", 2), ("report", 3), ("report", 4)]


def test_an_upstream_that_never_fires_at_that_time_skips_the_dependent_with_a_reason():
    dag = Dag("ops")
    dag.add(
        TaskSpec("report", Schedule.parse("0 6 * * 1-5", "UTC"), depends_on=("weekly",)),
        TaskSpec("weekly", Schedule.parse("0 6 * * 0", "UTC")),
    )
    plan = plan_catch_up(dag, [], start=at(2), end=at(6))
    assert plan.for_task("report") == []
    assert {item.reason for item in plan.skipped if item.task == "report"} == {"waiting on weekly"}


def test_a_skip_propagates_through_a_chain_of_dependencies():
    dag = Dag("ops")
    dag.add(
        TaskSpec("third", daily(), depends_on=("second",)),
        TaskSpec("second", daily(), depends_on=("first",)),
        TaskSpec("first", Schedule.parse("0 6 * * 0", "UTC")),
    )
    plan = plan_catch_up(dag, [], start=at(2), end=at(5))
    assert plan.runs == []
    reasons = {item.task: item.reason for item in plan.skipped}
    assert reasons["second"] == "waiting on first"
    assert reasons["third"] == "waiting on second"


# ---------------------------------------------------------------- depends_on_past


def test_the_first_occurrence_of_a_task_inside_the_window_has_no_past_wait():
    dag = Dag("ops")
    dag.add(TaskSpec("serial", daily(), depends_on_past=True))
    plan = plan_catch_up(dag, [], start=at(2), end=at(5))
    assert planned(plan, "serial") == [("serial", 2), ("serial", 3), ("serial", 4)]


def test_a_dropped_past_occurrence_blocks_the_ones_behind_it():
    """A cap that drops a day serialises everything downstream of that day."""
    dag = Dag("ops")
    dag.add(TaskSpec("serial", daily(), depends_on_past=True))
    plan = plan_catch_up(dag, [], start=at(2), end=at(6), max_runs_per_task=1)
    assert planned(plan, "serial") == [("serial", 2)]
    reasons = dict(dropped(plan, "serial"))
    assert reasons[3] == "limit"
    assert reasons[4] == "waiting on serial"
    assert reasons[5] == "waiting on serial"


def test_a_settled_past_occurrence_frees_the_next_one_despite_the_cap():
    dag = Dag("ops")
    dag.add(TaskSpec("serial", daily(), depends_on_past=True))
    plan = plan_catch_up(
        dag,
        [a_run("serial", at(2)), a_run("serial", at(3))],
        start=at(2),
        end=at(6),
        max_runs_per_task=1,
    )
    assert planned(plan, "serial") == [("serial", 4)]


# ---------------------------------------------------------------------------- cap


def test_the_cap_keeps_the_oldest_work_and_names_the_reason_for_the_rest():
    dag = Dag("ops")
    dag.add(TaskSpec("job", daily()))
    plan = plan_catch_up(dag, [], start=at(2), end=at(6), max_runs_per_task=2)
    assert planned(plan, "job") == [("job", 2), ("job", 3)]
    assert dropped(plan, "job") == [(4, "limit"), (5, "limit")]


def test_the_cap_applies_to_each_task_separately():
    dag = Dag("ops")
    dag.add(TaskSpec("first", daily()), TaskSpec("second", daily(), depends_on=("first",)))
    plan = plan_catch_up(dag, [], start=at(2), end=at(4), max_runs_per_task=1)
    assert planned(plan) == [("first", 2), ("second", 2)]


def test_without_a_cap_nothing_is_skipped_for_a_limit():
    dag = Dag("ops")
    dag.add(TaskSpec("job", daily()))
    plan = plan_catch_up(dag, [], start=at(2), end=at(6))
    assert all(item.reason != "limit" for item in plan.skipped)


# --------------------------------------------------------------------- ordering


def test_the_plan_is_ordered_by_time_then_by_dependency_depth():
    dag = Dag("ops")
    dag.add(
        TaskSpec("leaf", daily(), depends_on=("middle",)),
        TaskSpec("middle", daily(), depends_on=("root",)),
        TaskSpec("root", daily()),
        TaskSpec("solo", daily()),
    )
    plan = plan_catch_up(dag, [], start=at(2), end=at(3))
    assert [run.task for run in plan.runs] == ["root", "solo", "middle", "leaf"]


def test_ties_at_the_same_depth_break_on_the_task_name():
    dag = Dag("ops")
    dag.add(TaskSpec("zeta", daily()), TaskSpec("alpha", daily()))
    plan = plan_catch_up(dag, [], start=at(2), end=at(3))
    assert [run.task for run in plan.runs] == ["alpha", "zeta"]


# ------------------------------------------------------------------------ purity


def test_planned_and_skipped_together_partition_the_window():
    dag = Dag("ops")
    dag.add(TaskSpec("job", daily(), depends_on_past=True))
    plan = plan_catch_up(
        dag, [a_run("job", at(3), RunState.FAILED)], start=at(2), end=at(6), max_runs_per_task=2
    )
    seen = {(run.task, run.logical_time) for run in plan.runs} | {
        (item.task, item.logical_time) for item in plan.skipped
    }
    assert len(seen) == 4
    assert {(run.task, run.logical_time) for run in plan.runs}.isdisjoint(
        {(item.task, item.logical_time) for item in plan.skipped}
    )


def test_the_history_is_read_and_never_written():
    dag = Dag("ops")
    dag.add(TaskSpec("job", daily()))
    history = [a_run("job", at(3)), a_run("job", at(4), RunState.FAILED)]
    before = [(run.task, run.logical_time, run.state) for run in history]
    plan = plan_catch_up(dag, history, start=at(2), end=at(6))
    assert [(run.task, run.logical_time, run.state) for run in history] == before
    assert isinstance(plan, CatchUpPlan)


def test_the_same_window_planned_twice_returns_the_same_plan():
    dag = Dag("ops")
    dag.add(TaskSpec("second", daily(), depends_on=("first",)), TaskSpec("first", daily()))
    first = plan_catch_up(dag, [], start=at(2), end=at(5))
    second = plan_catch_up(dag, [], start=at(2), end=at(5))
    assert [(r.task, r.logical_time) for r in first.runs] == [
        (r.task, r.logical_time) for r in second.runs
    ]
