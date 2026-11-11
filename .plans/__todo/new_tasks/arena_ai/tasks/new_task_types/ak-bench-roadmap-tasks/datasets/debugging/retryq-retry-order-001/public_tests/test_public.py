"""The symptom a developer can reproduce: the second failure jumps the queue."""

from __future__ import annotations

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
