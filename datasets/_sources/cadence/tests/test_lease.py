"""One holder at a time, and the deadline is real."""

import pytest
from cadence.errors import LeaseHeld
from cadence.lease import LeaseBook


class Clock:
    def __init__(self) -> None:
        self.at = 1000.0

    def __call__(self) -> float:
        return self.at

    def advance(self, seconds: float) -> None:
        self.at += seconds


def test_a_held_resource_is_refused_until_the_deadline():
    clock = Clock()
    book = LeaseBook(clock)
    book.acquire("run:1", "alice", ttl=30)
    with pytest.raises(LeaseHeld):
        book.acquire("run:1", "bob", ttl=30)
    clock.advance(31)
    assert book.acquire("run:1", "bob", ttl=30).holder == "bob"


def test_renewing_a_live_lease_extends_it():
    clock = Clock()
    book = LeaseBook(clock)
    lease = book.acquire("run:1", "alice", ttl=30)
    clock.advance(20)
    renewed = book.renew(lease, ttl=30)
    clock.advance(20)
    assert book.is_valid(renewed)


def test_a_worker_may_take_back_a_resource_it_still_holds():
    clock = Clock()
    book = LeaseBook(clock)
    first = book.acquire("run:1", "alice", ttl=30)
    taken = book.takeover("run:1", "alice", epoch=first.epoch, ttl=30)
    assert taken.epoch == first.epoch
    assert book.is_valid(taken)
