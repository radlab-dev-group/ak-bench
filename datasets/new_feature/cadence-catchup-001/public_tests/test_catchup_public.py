"""What a developer can see without the hidden cases: the shape of the plan."""

from datetime import UTC, datetime

from cadence.catchup import CatchUpPlan, plan_catch_up
from cadence.dag import Dag, TaskSpec
from cadence.runs import Run, RunState
from cadence.schedule import Schedule


def at(day, hour=6):
    return datetime(2026, 11, day, hour, 0, tzinfo=UTC)


def a_run(task, moment, state=RunState.SUCCEEDED):
    return Run(run_id=f"{task}@{moment.isoformat()}", task=task, logical_time=moment, state=state)


def test_a_window_with_nothing_in_it_plans_the_occurrences_it_contains():
    daily = Schedule.parse("0 6 * * *", "UTC")
    dag = Dag("ops")
    dag.add(TaskSpec("job", daily))
    plan = plan_catch_up(dag, [], start=at(2), end=at(5))
    assert isinstance(plan, CatchUpPlan)
    assert [run.logical_time.day for run in plan.for_task("job")] == [2, 3, 4]
    assert plan.skipped == []


def test_a_succeeded_run_in_history_is_not_planned_again():
    daily = Schedule.parse("0 6 * * *", "UTC")
    dag = Dag("ops")
    dag.add(TaskSpec("job", daily))
    plan = plan_catch_up(dag, [a_run("job", at(3))], start=at(2), end=at(5))
    assert [run.logical_time.day for run in plan.for_task("job")] == [2, 4]
