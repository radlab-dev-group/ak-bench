"""The engine materialises runs and moves them through their states."""

import tempfile
from datetime import UTC, datetime, timedelta

from cadence.dag import Dag, TaskSpec
from cadence.log import WriteAheadLog
from cadence.runs import RunState
from cadence.schedule import Schedule
from cadence.scheduler import Scheduler, backoff_delay


def build(expression="0 6 * * *", **spec_kwargs):
    directory = tempfile.mkdtemp()
    dag = Dag("test")
    dag.add(TaskSpec("job", Schedule.parse(expression, "UTC"), **spec_kwargs))
    clock = {"now": datetime(2026, 11, 2, 6, 30, tzinfo=UTC)}
    engine = Scheduler(dag, WriteAheadLog(f"{directory}/job.log"), clock=lambda: clock["now"])
    return engine, clock


def test_a_due_occurrence_becomes_one_run():
    engine, _clock = build()
    engine.tick()
    assert [(run.task, run.state) for run in engine.runs()] == [("job", RunState.SCHEDULED)]


def test_a_run_is_materialised_once_across_many_ticks():
    engine, clock = build()
    engine.tick()
    clock["now"] += timedelta(minutes=5)
    engine.tick()
    assert len(engine.runs()) == 1


def test_claim_marks_the_run_running():
    engine, _clock = build()
    engine.tick()
    run = engine.runs()[0]
    engine.claim(run.run_id)
    assert engine.run(run.run_id).state is RunState.RUNNING


def test_a_failure_waits_out_its_backoff_and_comes_back():
    engine, clock = build(retries=2, backoff_seconds=60)
    engine.tick()
    run = engine.runs()[0]
    engine.claim(run.run_id)
    engine.fail(run.run_id)
    assert run.state is RunState.WAITING
    clock["now"] += timedelta(seconds=59)
    engine.tick()
    assert run.state is RunState.WAITING
    clock["now"] += timedelta(seconds=2)
    engine.tick()
    assert (run.state, run.attempt) == (RunState.SCHEDULED, 2)


def test_the_backoff_grows_by_a_factor_of_two():
    assert backoff_delay(60, 1) == timedelta(seconds=60)
    assert backoff_delay(60, 2) == timedelta(seconds=120)
