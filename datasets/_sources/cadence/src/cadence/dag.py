"""The task graph: what runs, what it waits for, and in which order.

A :class:`Dag` holds task specifications and the dependency edges between them.
It is a value: adding a task returns nothing and never reorders what is already
there, and asking for an order either answers with a topological order or
raises :class:`CycleError` naming the cycle.

Two different waits exist, and confusing them is how a scheduler double-runs
work:

``depends_on``
    another task's run **at the same logical time**. The daily report waits for
    the daily extract of the same day.

``depends_on_past``
    this task's own previous run, whatever time it belonged to. It is what
    makes a sequence serial: the second backfill day does not start before the
    first one succeeded.

A task may declare both; then both waits apply.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cadence.errors import CycleError, UnknownTask
from cadence.schedule import Schedule


@dataclass(frozen=True)
class TaskSpec:
    """What the scheduler knows about one task."""

    name: str
    schedule: Schedule
    depends_on: tuple[str, ...] = ()
    depends_on_past: bool = False
    retries: int = 0
    backoff_seconds: float = 60.0
    sla_seconds: int | None = None
    max_active_runs: int = 1

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("a task needs a name")
        if self.retries < 0:
            raise ValueError(f"retries cannot be negative, got {self.retries}")
        if self.backoff_seconds < 0:
            raise ValueError(f"backoff cannot be negative, got {self.backoff_seconds}")
        if self.max_active_runs < 1:
            raise ValueError(f"max_active_runs must be positive, got {self.max_active_runs}")
        if self.sla_seconds is not None and self.sla_seconds < 0:
            raise ValueError(f"sla_seconds cannot be negative, got {self.sla_seconds}")


@dataclass
class Dag:
    """Tasks and the edges between them, with a deterministic topological order."""

    name: str = "dag"
    _tasks: dict[str, TaskSpec] = field(default_factory=dict, repr=False)

    def add(self, *specs: TaskSpec) -> None:
        for spec in specs:
            if spec.name in self._tasks:
                raise ValueError(f"task {spec.name!r} is already in the DAG")
            self._tasks[spec.name] = spec
        self.check()

    def require(self, name: str) -> TaskSpec:
        try:
            return self._tasks[name]
        except KeyError as exc:
            raise UnknownTask(name) from exc

    def names(self) -> list[str]:
        return sorted(self._tasks)

    def __contains__(self, name: object) -> bool:
        return name in self._tasks

    def __len__(self) -> int:
        return len(self._tasks)

    def upstream(self, name: str) -> tuple[str, ...]:
        """The task's direct dependencies, in the order they were declared."""
        return self.require(name).depends_on

    def downstream(self, name: str) -> list[str]:
        """Tasks that wait on this one, ordered by name."""
        return sorted(other for other in self._tasks if name in self._tasks[other].depends_on)

    def closure(self, name: str) -> list[str]:
        """Everything the task ultimately waits for, nearest first, without the task."""
        seen: set[str] = set()
        frontier = list(self.upstream(name))
        ordered: list[str] = []
        while frontier:
            current = frontier.pop(0)
            if current in seen:
                continue
            seen.add(current)
            ordered.append(current)
            frontier.extend(self.upstream(current))
        return ordered

    def check(self) -> None:
        """Refuse an unknown dependency and refuse a cycle; name what was found."""
        for task_name, spec in sorted(self._tasks.items()):
            for dependency in spec.depends_on:
                if dependency not in self._tasks:
                    raise UnknownTask(f"{task_name} waits for unknown task {dependency!r}")
                if dependency == task_name:
                    raise CycleError([task_name, task_name])
        self.order()

    def order(self) -> list[str]:
        """A topological order; ties break on the task name, so it is reproducible."""
        remaining = {name: set(self._tasks[name].depends_on) for name in self._tasks}
        ordered: list[str] = []
        while remaining:
            ready = sorted(name for name, waits in remaining.items() if not waits)
            if not ready:
                raise CycleError(self._find_cycle(sorted(remaining)))
            for name in ready:
                ordered.append(name)
                del remaining[name]
            for waits in remaining.values():
                waits.difference_update(ready)
        return ordered

    def _find_cycle(self, names: list[str]) -> list[str]:
        """The cycle itself, for an error message a human can act on."""
        state: dict[str, str] = {}
        path: list[str] = []

        def visit(current: str) -> list[str] | None:
            state[current] = "open"
            path.append(current)
            for dependency in sorted(self._tasks[current].depends_on):
                if dependency not in names:
                    continue
                if state.get(dependency) == "open":
                    return [*path[path.index(dependency) :], dependency]
                if state.get(dependency) is None:
                    found = visit(dependency)
                    if found:
                        return found
            path.pop()
            state[current] = "closed"
            return None

        for name in names:
            if state.get(name) is None:
                found = visit(name)
                if found:
                    return found
        return names
