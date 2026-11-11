"""The finished part of the fixture: ordering without failures.

The suite deliberately never fails two tasks in a row, so a defect in
the retry order is invisible here.
"""

from __future__ import annotations

import pytest

from retryq import RetryQueue


def test_tasks_are_taken_in_enqueue_order():
    queue = RetryQueue()
    queue.enqueue("a")
    queue.enqueue("b")
    queue.enqueue("c")
    assert queue.next_task() == "a"
    assert queue.next_task() == "b"
    assert queue.next_task() == "c"
    assert queue.next_task() is None


def test_a_single_failed_task_is_taken_again():
    queue = RetryQueue()
    queue.enqueue("a")
    assert queue.next_task() == "a"
    queue.enqueue("a")
    queue.fail("a")
    assert queue.next_task() == "a"


def test_failing_an_unknown_task_is_refused():
    with pytest.raises(ValueError):
        RetryQueue().fail("nope")


def test_len_counts_waiting_tasks():
    queue = RetryQueue()
    queue.enqueue("a")
    queue.enqueue("b")
    assert len(queue) == 2
