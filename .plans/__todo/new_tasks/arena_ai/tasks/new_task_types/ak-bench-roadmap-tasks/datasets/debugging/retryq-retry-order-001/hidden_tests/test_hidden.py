"""The failing scenario, proven from every side.

These tests fail on the base commit (the defect is in the base code) and
pass once the retry order is repaired.
"""

from __future__ import annotations

import pytest

from retryq import RetryQueue


def test_two_failures_go_behind_the_waiting_tasks():
    queue = RetryQueue()
    queue.enqueue("a")
    queue.enqueue("b")
    queue.enqueue("c")
    assert queue.next_task() == "a"
    queue.fail("a")
    assert queue.next_task() == "b"
    queue.fail("b")
    assert queue.next_task() == "c"
    assert queue.next_task() == "a"
    assert queue.next_task() == "b"


def test_a_failure_goes_behind_newly_enqueued_tasks():
    queue = RetryQueue()
    queue.enqueue("a")
    queue.enqueue("b")
    assert queue.next_task() == "a"
    queue.fail("a")
    queue.enqueue("c")
    assert queue.next_task() == "b"
    assert queue.next_task() == "a"
    assert queue.next_task() == "c"


def test_repeated_failures_cycle_in_order():
    queue = RetryQueue()
    queue.enqueue("a")
    queue.enqueue("b")
    for _ in range(2):
        assert queue.next_task() == "a"
        queue.fail("a")
        assert queue.next_task() == "b"
        queue.fail("b")


def test_plain_order_and_refusals_still_work():
    queue = RetryQueue()
    queue.enqueue("a")
    queue.enqueue("b")
    assert queue.next_task() == "a"
    assert queue.next_task() == "b"
    assert queue.next_task() is None
    with pytest.raises(ValueError):
        queue.fail("nope")
