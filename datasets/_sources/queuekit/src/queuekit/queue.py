"""A FIFO queue on a linked list.

``enqueue`` adds at the back, ``dequeue`` takes from the front (or
returns ``None`` when empty), and ``len`` counts the waiting items.
"""

from __future__ import annotations


class _Node:
    def __init__(self, value, next_node=None):
        self.value = value
        self.next = next_node


class Queue:
    """A first-in-first-out queue."""

    def __init__(self) -> None:
        self._head: _Node | None = None
        self._tail: _Node | None = None
        self._size = 0

    def enqueue(self, value) -> None:
        """Add ``value`` at the back."""
        node = _Node(value)
        if self._tail is None:
            self._head = self._tail = node
        else:
            self._tail.next = node
            self._tail = node
        self._size += 1

    def dequeue(self):
        """Take the front value, or ``None`` when empty."""
        if self._head is None:
            return None
        value = self._head.value
        self._head = self._head.next
        if self._head is None:
            self._tail = None
        self._size -= 1
        return value

    def __len__(self) -> int:
        return self._size
