"""The fencing rule, enforced where a defect can still hide.

A lease is the only thing standing between two workers and the same run, so
the tests are written as accounting around one question: after a request the
book should refuse, who holds the resource, with which epoch, and is the
worker that was working still able to work? Every refusal has to leave all
three exactly as they were, because changing any of them is a fencing break.
"""

import pytest
from cadence.errors import LeaseExpired, LeaseHeld
from cadence.lease import LeaseBook


class Clock:
    def __init__(self) -> None:
        self.at = 1000.0

    def __call__(self) -> float:
        return self.at

    def advance(self, seconds: float) -> None:
        self.at += seconds


def book() -> tuple[LeaseBook, Clock]:
    clock = Clock()
    return LeaseBook(clock), clock


def taken_over_by_someone_else() -> tuple[LeaseBook, Clock, "object"]:
    """Alice holds a resource, lets it die, and bob takes it over."""
    leases, clock = book()
    first = leases.acquire("run:1", "alice", ttl=30)
    clock.advance(31)
    leases.acquire("run:1", "bob", ttl=30)
    return leases, clock, first


# ------------------------------------------------------------- stale epochs


def test_a_stale_epoch_cannot_take_a_live_lease_back():
    leases, _clock, first = taken_over_by_someone_else()
    with pytest.raises(LeaseHeld):
        leases.takeover("run:1", "alice", epoch=first.epoch, ttl=30)


def test_a_refused_takeover_leaves_the_current_holder_holding():
    leases, _clock, first = taken_over_by_someone_else()
    with pytest.raises(LeaseHeld):
        leases.takeover("run:1", "alice", epoch=first.epoch, ttl=30)
    assert leases.holder_of("run:1").holder == "bob"


def test_a_refused_takeover_does_not_move_the_deadline():
    leases, clock = book()
    first = leases.acquire("run:1", "alice", ttl=30)
    clock.advance(31)
    second = leases.acquire("run:1", "bob", ttl=90)
    with pytest.raises(LeaseHeld):
        leases.takeover("run:1", "alice", epoch=first.epoch, ttl=10)
    clock.advance(60)
    assert leases.holder_of("run:1") == second


def test_a_refused_takeover_does_not_burn_an_epoch():
    leases, clock = book()
    first = leases.acquire("run:1", "alice", ttl=30)
    clock.advance(31)
    second = leases.acquire("run:1", "bob", ttl=30)
    with pytest.raises(LeaseHeld):
        leases.takeover("run:1", "alice", epoch=first.epoch, ttl=30)
    clock.advance(31)
    third = leases.acquire("run:1", "carol", ttl=30)
    assert third.epoch == second.epoch + 1


def test_an_epoch_from_another_resource_is_stale_here_too():
    """Epochs are per-resource: the number a different resource carries is no pass here."""
    leases, clock = book()
    leases.acquire("run:other", "alice", ttl=30)
    clock.advance(31)
    stale = leases.acquire("run:other", "alice", ttl=30)
    held = leases.acquire("run:1", "bob", ttl=30)
    assert stale.epoch > held.epoch
    with pytest.raises(LeaseHeld):
        leases.takeover("run:1", "alice", epoch=stale.epoch, ttl=30)


def test_a_much_older_epoch_is_refused_as_stale_as_any_other():
    leases, clock = book()
    oldest = leases.acquire("run:1", "alice", ttl=10)
    for index in range(3):
        clock.advance(11)
        leases.acquire("run:1", f"worker{index}", ttl=10)
    with pytest.raises(LeaseHeld):
        leases.takeover("run:1", "alice", epoch=oldest.epoch, ttl=10)
    assert leases.holder_of("run:1").holder == "worker2"


# ------------------------------------------------------- what must still work


def test_a_request_carrying_the_current_epoch_still_takes_it_back():
    leases, _clock = book()
    first = leases.acquire("run:1", "alice", ttl=30)
    taken = leases.takeover("run:1", "alice", epoch=first.epoch, ttl=30)
    assert taken.holder == "alice"
    assert leases.is_valid(taken)


def test_a_takeover_of_a_free_resource_still_acquires_it():
    leases, _clock = book()
    taken = leases.takeover("run:1", "alice", epoch=1, ttl=30)
    assert taken.holder == "alice"
    assert taken.epoch == 1


def test_the_worker_that_let_its_lease_die_cannot_renew_it():
    leases, clock = book()
    first = leases.acquire("run:1", "alice", ttl=30)
    clock.advance(31)
    with pytest.raises(LeaseExpired):
        leases.renew(first, ttl=30)


# ------------------------------------------------------- through the scheduler


def test_a_worker_that_lost_its_run_cannot_keep_heartbeat_on_it():
    """The engine is where a missing fence becomes duplicated work."""
    import tempfile
    from datetime import UTC, datetime

    from cadence.dag import Dag, TaskSpec
    from cadence.errors import IllegalRunTransition
    from cadence.log import WriteAheadLog
    from cadence.schedule import Schedule
    from cadence.scheduler import Scheduler

    directory = tempfile.mkdtemp()
    dag = Dag("ops")
    dag.add(TaskSpec("job", Schedule.parse("0 6 * * *", "UTC")))
    clock = {"now": datetime(2026, 11, 2, 6, 30, tzinfo=UTC)}
    engine = Scheduler(
        dag,
        WriteAheadLog(f"{directory}/job.log"),
        clock=lambda: clock["now"],
        owner="alice",
        lease_seconds=30.0,
    )
    engine.tick()
    run = engine.runs()[0]
    engine.claim(run.run_id)

    # the lease dies, bob takes the resource, and alice reports in
    clock["now"] = datetime(2026, 11, 2, 6, 31, tzinfo=UTC)
    engine.leases.acquire(f"run:{run.run_id}", "bob", ttl=30)
    with pytest.raises(IllegalRunTransition):
        engine.heartbeat(run.run_id)
    assert engine.leases.holder_of(f"run:{run.run_id}").holder == "bob"
