"""The graph orders its tasks and refuses the two shapes that cannot run."""

from cadence.dag import CycleError, Dag, TaskSpec
from cadence.errors import UnknownTask
from cadence.schedule import Schedule


def _dag() -> Dag:
    dag = Dag("test")
    daily = Schedule.parse("0 6 * * *", "UTC")
    dag.add(TaskSpec("b", daily, depends_on=("a",)), TaskSpec("a", daily), TaskSpec("c", daily))
    return dag


def test_order_places_a_task_after_what_it_waits_for():
    order = _dag().order()
    assert order.index("a") < order.index("b")
    assert order.index("a") < order.index("c")


def test_a_cycle_is_named():
    dag = Dag("bad")
    daily = Schedule.parse("0 6 * * *", "UTC")
    try:
        dag.add(TaskSpec("x", daily, depends_on=("y",)), TaskSpec("y", daily, depends_on=("x",)))
    except CycleError as error:
        assert set(error.cycle) == {"x", "y"}
    else:  # pragma: no cover - the add must fail
        raise AssertionError("a cycle must be refused")


def test_an_unknown_dependency_is_refused():
    dag = Dag("bad")
    import pytest

    with pytest.raises(UnknownTask):
        dag.add(TaskSpec("x", Schedule.parse("0 6 * * *", "UTC"), depends_on=("ghost",)))
