"""The refactoring, proven: target structure plus preserved behaviour.

These tests fail on the base commit (the target module does not exist)
and pass once the backend is a deque.
"""

from __future__ import annotations

from pathlib import Path

from queuekit import Queue
from queuekit.backend import DequeQueue


def test_deque_queue_behaviour():
    queue = DequeQueue()
    assert len(queue) == 0
    assert queue.dequeue() is None
    queue.enqueue("a")
    queue.enqueue("b")
    assert len(queue) == 2
    assert queue.dequeue() == "a"
    queue.enqueue("c")
    assert queue.dequeue() == "b"
    assert queue.dequeue() == "c"
    assert len(queue) == 0


def test_deque_queue_is_backed_by_a_deque():
    source = Path(DequeQueue.__module__.replace(".", "/") + ".py")
    # Resolve relative to the installed package location.
    import queuekit.backend as backend

    source = Path(backend.__file__)
    assert "deque" in source.read_text(encoding="utf-8")


def test_queue_behaviour_is_unchanged():
    queue = Queue()
    queue.enqueue("a")
    queue.enqueue("b")
    queue.enqueue("c")
    assert queue.dequeue() == "a"
    assert queue.dequeue() == "b"
    assert queue.dequeue() == "c"
    assert queue.dequeue() is None
    assert len(queue) == 0
