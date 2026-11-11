"""The target structure, in miniature: DequeQueue exists and Queue holds."""

from __future__ import annotations

from queuekit import Queue
from queuekit.backend import DequeQueue


def test_deque_queue_is_first_in_first_out():
    queue = DequeQueue()
    queue.enqueue("a")
    queue.enqueue("b")
    assert queue.dequeue() == "a"
    assert queue.dequeue() == "b"
    assert queue.dequeue() is None


def test_queue_still_works():
    queue = Queue()
    queue.enqueue("a")
    assert queue.dequeue() == "a"
