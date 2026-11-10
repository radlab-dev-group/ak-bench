"""Logical time and seeded randomness."""

import pytest

from tidewater.clock import EventQueue, LogicalClock, NodeClock
from tidewater.errors import ConfigurationError
from tidewater.rng import SeedTree, Stream, derive_seed


def test_logical_clock_only_moves_forward():
    clock = LogicalClock()
    assert clock.now == 0
    assert clock.advance() == 1
    assert clock.advance(5) == 6
    with pytest.raises(ConfigurationError):
        clock.advance(0)


def test_node_clock_rate_and_offset():
    clock = NodeClock(rate=1, offset=0)
    assert clock.tick() == 1
    clock.set_skew(rate=3)
    assert clock.tick() == 4
    assert clock.describe() == "rate=3 offset=0"
    with pytest.raises(ConfigurationError):
        clock.set_skew(rate=0)


def test_event_queue_orders_by_time_then_insertion():
    queue = EventQueue()
    queue.push(5, "b")
    queue.push(3, "a")
    queue.push(5, "c")
    assert [e.kind for e in queue.pop_due(4)] == ["a"]
    assert [e.kind for e in queue.pop_due(5)] == ["b", "c"]
    assert queue.pop_due(99) == []


def test_event_queue_remove_if():
    queue = EventQueue()
    for i in range(6):
        queue.push(i, "k", payload=i)
    removed = queue.remove_if(lambda e: e.payload % 2 == 0)
    assert removed == 3
    assert [e.payload for e in queue.drain()] == [1, 3, 5]


def test_derive_seed_is_stable_and_label_sensitive():
    assert derive_seed(7, "n1", "election") == derive_seed(7, "n1", "election")
    assert derive_seed(7, "n1", "election") != derive_seed(7, "n2", "election")
    assert derive_seed(7, "n1") != derive_seed(8, "n1")


def test_streams_are_independent_per_node():
    tree = SeedTree(42)
    a = tree.stream("n1", "election")
    b = tree.stream("n2", "election")
    first_b = [b.randrange(1000) for _ in range(5)]
    # Drawing from a must not perturb b's sequence.
    for _ in range(50):
        a.randrange(1000)
    fresh = SeedTree(42).stream("n2", "election")
    assert [fresh.randrange(1000) for _ in range(5)] == first_b
    assert tree.stream("n1", "election") is a


def test_election_timeout_is_in_half_open_window():
    stream = Stream(seed=3, label="t")
    draws = [stream.election_timeout(50) for _ in range(500)]
    assert min(draws) >= 50
    assert max(draws) <= 99
    assert 50 in draws and 99 in draws  # both ends of [T, 2T) are reachable
    assert stream.draws == 500
    with pytest.raises(ValueError):
        stream.election_timeout(0)
