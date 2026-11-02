"""The invariant a developer can be told about, without the exact cases."""

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


def test_a_holder_taking_its_own_resource_back_by_its_epoch_still_works():
    clock = Clock()
    book = LeaseBook(clock)
    first = book.acquire("run:1", "alice", ttl=30)
    taken = book.takeover("run:1", "alice", epoch=first.epoch, ttl=30)
    assert book.is_valid(taken)


def test_someone_else_cannot_take_a_live_lease_while_it_is_held():
    clock = Clock()
    book = LeaseBook(clock)
    book.acquire("run:1", "alice", ttl=30)
    with pytest.raises(LeaseHeld):
        book.acquire("run:1", "bob", ttl=30)
    assert book.holder_of("run:1").holder == "alice"
