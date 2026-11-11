"""The finished part of the fixture: queue behaviour.

These tests pin the behaviour the refactoring must preserve.
"""

from __future__ import annotations

from queuekit import Queue


def test_first_in_first_out():
    queue = Queue()
    queue.enqueue("a")
    queue.enqueue("b")
    queue.enqueue("c")
    assert queue.dequeue() == "a"
    assert queue.dequeue() == "b"
    assert queue.dequeue() == "c"
    assert queue.dequeue() is None


def test_len_counts_waiting_items():
    queue = Queue()
    queue.enqueue("a")
    queue.enqueue("b")
    assert len(queue) == 2
    queue.dequeue()
    assert len(queue) == 1


def test_interleaved_enqueue_and_dequeue():
    queue = Queue()
    queue.enqueue("a")
    assert queue.dequeue() == "a"
    queue.enqueue("b")
    assert queue.dequeue() == "b"
    assert len(queue) == 0
