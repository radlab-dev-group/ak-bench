"""A queue with retries.

Tasks are taken in the order they were queued (first in, first out). When
a task fails, it is re-queued at the back, behind everything already
waiting, so a failing task cannot starve the tasks behind it.
"""

from __future__ import annotations

from collections import deque


class RetryQueue:
    """Tasks in order, with failed tasks re-queued at the back."""

    def __init__(self) -> None:
        self._tasks: deque[str] = deque()
        self._known: set[str] = set()

    def enqueue(self, task_id: str) -> None:
        """Add a task to the back of the queue."""
        self._known.add(task_id)
        self._tasks.append(task_id)

    def fail(self, task_id: str) -> None:
        """Re-queue a failed task at the back, behind everything waiting."""
        if task_id not in self._known:
            raise ValueError(f"unknown task {task_id!r}")
        if task_id in self._tasks:
            self._tasks.remove(task_id)
        self._tasks.appendleft(task_id)

    def next_task(self) -> str | None:
        """Take the next task, or ``None`` when the queue is empty."""
        if not self._tasks:
            return None
        return self._tasks.popleft()

    def __len__(self) -> int:
        return len(self._tasks)
