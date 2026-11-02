"""The engine: what a schedule means when something has to actually run.

A :class:`Scheduler` turns the schedules of a :class:`~cadence.dag.Dag` into
runs, moves them through their states, and writes every move to a
:class:`~cadence.log.WriteAheadLog` before acting on it. It is driven by an
injected clock: ``tick(now)`` is the whole of its relationship with time, so a
test can replay a week in a loop and a crash can be simulated by throwing the
object away and calling :meth:`recover` on the log.

Materialising runs
    A run exists for an occurrence of a task once that occurrence is at or
    before ``now`` and the run may start. "May start" means:

    * the task has fewer than ``max_active_runs`` runs in an active state
      (``scheduled`` or ``running``);
    * every task it ``depends_on`` has run at or before this occurrence, and its
      newest such run **succeeded**. Waiting for "the upstream ran sometime"
      would let a Monday report run off a Friday extract, and waiting for a run
      at the identical instant would deadlock two tasks on staggered schedules;
    * if it ``depends_on_past``, its most recent earlier run has succeeded.

    Occurrences before the scheduler's ``catch_up_start`` are never materialised:
    a scheduler started today does not decide to run yesterday.

Retrying
    A failed run whose attempt count still fits inside ``retries`` waits and is
    offered again. The wait is exponential from the task's ``backoff_seconds``:
    attempt *n* waits ``backoff_seconds * 2 ** (n - 1)``, so with 60 seconds the
    waits are 60, 120, 240, 480 — and nothing else. A retry is the same run with
    a higher attempt counter, not a new run. Once the attempts are used up the
    run is ``failed``, and only an explicit rerun moves it again.

Recovering
    ``recover`` folds the log back into runs and states. It is idempotent by
    construction: the log keys each transition by the run and the attempt it
    belongs to, so replaying a log that was written twice changes nothing. A
    run that was ``running`` when the process died is ``running`` after recovery
    too — the engine does not guess that a dead worker's work was lost, and a
    lease is what resolves that question.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from cadence.dag import Dag
from cadence.errors import IllegalRunTransition, LeaseExpired, LeaseHeld, UnknownRun
from cadence.lease import LeaseBook
from cadence.log import Record, WriteAheadLog, fold
from cadence.runs import TERMINAL, Run, RunState, blocked_before, succeeded_at


def backoff_delay(seconds: float, attempt: int) -> timedelta:
    """The wait before attempt ``attempt`` is offered again: 60, 120, 240, 480."""
    if attempt < 1:
        raise ValueError(f"attempt counting starts at 1, got {attempt}")
    return timedelta(seconds=seconds * (2 ** (attempt - 1)))


@dataclass
class Scheduler:
    """One engine over one DAG, its clock, its log and its lease book."""

    dag: Dag
    log: WriteAheadLog
    clock: Callable[[], datetime]
    leases: LeaseBook = field(default=None)  # type: ignore[assignment]
    owner: str = "engine"
    lease_seconds: float = 90.0
    catch_up_start: datetime | None = None

    def __post_init__(self) -> None:
        if self.leases is None:
            self.leases = LeaseBook(clock=lambda: self.now().timestamp())
        if self.catch_up_start is not None and self.catch_up_start.tzinfo is None:
            raise ValueError("catch_up_start needs a time zone")

    # clock -----------------------------------------------------------------

    def now(self) -> datetime:
        moment = self.clock()
        if moment.tzinfo is None:
            raise ValueError("the scheduler clock must return time zone aware instants")
        return moment

    # runs ------------------------------------------------------------------

    def runs(self) -> list[Run]:
        return sorted(
            self._runs.values(),
            key=lambda run: (run.logical_time, run.task, run.attempt),
        )

    def run(self, run_id: str) -> Run:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise UnknownRun(run_id) from exc

    def open_runs(self) -> list[Run]:
        return [run for run in self.runs() if run.open]

    # materialising ---------------------------------------------------------

    def due(self, limit_now: datetime | None = None) -> list[tuple[str, datetime]]:
        """Occurrences that exist and may start, oldest logical time first.

        The order is a topological order within one logical time, so a dependent
        task is never offered before the task it waits for has been offered.
        """
        moment = limit_now if limit_now is not None else self.now()
        offered: list[tuple[str, datetime]] = []
        for name in self.dag.order():
            spec = self.dag.require(name)
            start = (
                self.catch_up_start
                if self.catch_up_start is not None
                else moment - timedelta(days=1)
            )
            if moment <= start:
                continue
            horizon = moment + timedelta(microseconds=1)
            for occurrence in spec.schedule.occurrences_between(start, horizon):
                if self._has_run(name, occurrence):
                    continue
                if self._active_count(name) >= spec.max_active_runs:
                    continue
                if not self._dependencies_met(name, occurrence):
                    continue
                offered.append((name, occurrence))
        return sorted(offered, key=lambda pair: (pair[1], self._depth(pair[0])))

    def tick(self, limit_now: datetime | None = None) -> list[Run]:
        """Materialise every occurrence that is due right now, and retry what is due a retry."""
        moment = limit_now if limit_now is not None else self.now()
        created = [self._create(task, occurrence) for task, occurrence in self.due(moment)]
        created.extend(self.retry_ready(moment))
        return created

    # state moves -----------------------------------------------------------

    def claim(self, run_id: str, *, holder: str | None = None) -> Run:
        """Take the lease of a run and mark it running; the only way work starts."""
        run = self.run(run_id)
        owner = holder if holder is not None else self.owner
        lease = self.leases.acquire(_resource(run), owner, ttl=self.lease_seconds)
        self._append("started", run, {"holder": owner, "epoch": lease.epoch})
        run.state = RunState.RUNNING
        run.started_at = self.now()
        run.attempts.append(self.now())
        run.lease_epoch = lease.epoch  # type: ignore[attr-defined]
        return run

    def succeed(self, run_id: str) -> Run:
        run = self.run(run_id)
        run.moved_to(RunState.SUCCEEDED)
        self._append("succeeded", run, {})
        run.state = RunState.SUCCEEDED
        run.finished_at = self.now()
        self._release(run)
        return run

    def fail(self, run_id: str, *, reason: str = "") -> Run:
        """Record a failure: retry with a wait if attempts remain, otherwise fail for good."""
        run = self.run(run_id)
        run.moved_to(RunState.FAILED)
        spec = self.dag.require(run.task)
        if run.attempt <= spec.retries:
            delay = backoff_delay(spec.backoff_seconds, run.attempt)
            self._append("retrying", run, {"reason": reason, "wait_seconds": delay.total_seconds()})
            run.state = RunState.WAITING
            run.next_attempt_at = self.now() + delay
        else:
            self._append("failed", run, {"reason": reason})
            run.state = RunState.FAILED
            run.finished_at = self.now()
        self._release(run)
        return run

    def retry_ready(self, moment: datetime | None = None) -> list[Run]:
        """Offer back every run whose backoff has elapsed."""
        instant = moment if moment is not None else self.now()
        ready: list[Run] = []
        for run in list(self._runs.values()):
            if run.state is not RunState.WAITING:
                continue
            if run.next_attempt_at is not None and run.next_attempt_at > instant:
                continue
            self._append("offered", run, {"attempt": run.attempt + 1})
            run.attempt += 1
            run.state = RunState.SCHEDULED
            run.next_attempt_at = None
            run.started_at = None
            ready.append(run)
        return ready

    def rerun(self, run_id: str) -> Run:
        """An operator's decision: put a finished run back at the start of the queue."""
        run = self.run(run_id)
        run.moved_to(RunState.SCHEDULED)
        self._append("rerun", run, {})
        run.state = RunState.SCHEDULED
        run.attempt = 1
        run.started_at = None
        run.finished_at = None
        run.next_attempt_at = None
        return run

    def heartbeat(self, run_id: str, *, holder: str | None = None) -> Run:
        """Extend the lease of a run this worker is still working on."""
        run = self.run(run_id)
        owner = holder if holder is not None else self.owner
        lease = self._lease_of(run)
        try:
            self.leases.renew(lease, ttl=self.lease_seconds)
        except (LeaseHeld, LeaseExpired) as exc:
            raise IllegalRunTransition(
                f"{run.run_id}: the lease is no longer this worker's to extend"
            ) from exc
        self._append("heartbeat", run, {"holder": owner})
        return run

    # recovery --------------------------------------------------------------

    def recover(self) -> list[Run]:
        """Rebuild the runs from the log; running what was written twice changes nothing."""
        self._runs = {}
        for record in self.log.records():
            self._apply(record)
        return self.runs()

    def snapshot(self) -> dict[str, str]:
        """Task to the state of its newest run — the one question operators ask."""
        newest: dict[str, Run] = {}
        for run in self.runs():
            current = newest.get(run.task)
            if current is None or (run.logical_time, run.attempt) > (
                current.logical_time,
                current.attempt,
            ):
                newest[run.task] = run
        return {task: run.state.value for task, run in sorted(newest.items())}

    # internals -------------------------------------------------------------

    _runs: dict[str, Run] = field(default_factory=dict, repr=False, init=False)

    def _create(self, task: str, logical_time: datetime) -> Run:
        run_id = run_key(task, logical_time)
        run = Run(run_id=run_id, task=task, logical_time=logical_time, scheduled_at=self.now())
        self._append("scheduled", run, {})
        self._runs[run_id] = run
        return run

    def _append(self, kind: str, run: Run, payload: dict[str, object]) -> Record:
        return self.log.append(
            kind,
            {
                "subject": run.run_id,
                "task": run.task,
                "logical_time": run.logical_time.isoformat(),
                "attempt": run.attempt,
                **payload,
            },
            at=self.now().timestamp(),
            idempotency_key=f"{run.run_id}:{kind}:{run.attempt}",
        )

    def _apply(self, record: Record) -> None:
        subject = str(record.payload.get("subject", ""))
        if not subject:
            return
        logical_raw = str(record.payload.get("logical_time", ""))
        task = str(record.payload.get("task", subject.split("@")[0]))
        attempt = int(record.payload.get("attempt", 1) or 1)
        run = self._runs.get(subject)
        if run is None:
            run = Run(
                run_id=subject,
                task=task,
                logical_time=datetime.fromisoformat(logical_raw) if logical_raw else epoch(),
            )
            self._runs[subject] = run
        if record.kind == "scheduled":
            run.attempt = attempt
            run.state = RunState.SCHEDULED
        elif record.kind == "started":
            run.state = RunState.RUNNING
            run.attempt = attempt
            run.started_at = datetime.fromtimestamp(record.at, tz=UTC)
        elif record.kind == "succeeded":
            run.state = RunState.SUCCEEDED
            run.finished_at = datetime.fromtimestamp(record.at, tz=UTC)
        elif record.kind == "retrying":
            run.state = RunState.WAITING
            wait = float(record.payload.get("wait_seconds", 0) or 0)
            run.next_attempt_at = datetime.fromtimestamp(record.at + wait, tz=UTC)
        elif record.kind == "offered":
            run.attempt = int(record.payload.get("attempt", attempt + 1) or attempt)
            run.state = RunState.SCHEDULED
            run.next_attempt_at = None
        elif record.kind == "failed":
            run.state = RunState.FAILED
            run.finished_at = datetime.fromtimestamp(record.at, tz=UTC)
        elif record.kind == "rerun":
            run.state = RunState.SCHEDULED
            run.attempt = 1
            run.next_attempt_at = None

    def _has_run(self, task: str, logical_time: datetime) -> bool:
        return run_key(task, logical_time) in self._runs

    def _active_count(self, task: str) -> int:
        return sum(1 for run in self._runs.values() if run.task == task and run.active)

    def _dependencies_met(self, task: str, logical_time: datetime) -> bool:
        spec = self.dag.require(task)
        runs = list(self._runs.values())
        for upstream in spec.depends_on:
            if not succeeded_at(runs, upstream, logical_time):
                return False
        if spec.depends_on_past:
            return blocked_before(runs, task, logical_time) is None
        return True

    def _depth(self, task: str) -> int:
        return len(self.dag.closure(task))

    def _release(self, run: Run) -> None:
        lease = getattr(run, "lease_epoch", None)
        if lease is None:
            return
        self.leases.release(_lease(run, lease, self.owner))
        delattr(run, "lease_epoch")

    def _lease_of(self, run: Run):
        epoch_value = getattr(run, "lease_epoch", 0)
        return _lease(run, epoch_value, self.owner)


def run_key(task: str, logical_time: datetime) -> str:
    """The identity of a run: a task and one logical time."""
    return f"{task}@{logical_time.isoformat()}"


def _resource(run: Run) -> str:
    return f"run:{run.run_id}"


def _lease(run: Run, epoch_value: int, holder: str):
    from cadence.lease import Lease

    return Lease(
        resource=_resource(run),
        holder=holder,
        epoch=epoch_value,
        taken_at=0.0,
        until=float("inf"),
    )


def epoch() -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC)


__all__ = ["TERMINAL", "Scheduler", "backoff_delay", "fold", "run_key"]
