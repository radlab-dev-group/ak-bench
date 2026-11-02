"""Public single-writer queue. Reopen after every exception from a crash hook."""

import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from .codec import canonical
from .journal import Journal
from .model import Lease, Task, integer, name
from .recovery import recover
from .snapshot import Snapshots


def no_hook(point: str) -> None:
    pass


class Queue:
    def __init__(self, path: Path, *, hook: Callable[[str], None] = no_hook) -> None:
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.hook = hook
        self.journal = Journal(self.path, hook)
        self.snapshots = Snapshots(self.path, hook)
        self.sequence, self.state = recover(self.snapshots, self.journal)

    def _commit(self, commands: list[dict]) -> None:
        if not commands:
            return
        commands = json.loads(canonical(commands))
        candidate = self.state.clone()
        candidate.apply(commands)
        next_sequence = self.sequence + 1
        self.journal.append(next_sequence, commands)
        self.state = candidate
        self.sequence = next_sequence

    def put(
        self,
        task_id: str,
        payload: dict,
        *,
        key: str | None = None,
        available_at: int = 0,
        max_attempts: int = 3,
    ) -> str:
        self.put_many(
            [
                {
                    "task_id": task_id,
                    "payload": payload,
                    "key": task_id if key is None else key,
                    "available_at": available_at,
                    "max_attempts": max_attempts,
                }
            ]
        )
        return task_id

    def put_many(self, requests: list[dict]) -> None:
        if not isinstance(requests, list):
            raise ValueError("requests must be a list")
        commands = [{"op": "put", **request} for request in requests]
        self._commit(commands)

    def reap(self, now: int) -> None:
        integer(now, "now")
        commands = [
            {"op": "expire", "task_id": task.task_id, "now": now}
            for task in sorted(self.state.tasks.values(), key=lambda item: item.task_id)
            if task.status == "leased" and task.deadline <= now
        ]
        self._commit(commands)

    def reserve(self, worker: str, *, now: int, lease_seconds: int, limit: int = 1) -> list[Lease]:
        name(worker, "worker")
        integer(now, "now")
        integer(lease_seconds, "lease_seconds", 1)
        integer(limit, "limit", 1)
        self.reap(now)
        eligible = sorted(
            (
                task
                for task in self.state.tasks.values()
                if task.status == "ready" and task.available_at <= now
            ),
            key=lambda task: (task.available_at, task.task_id),
        )[:limit]
        self._commit(
            [
                {
                    "op": "lease",
                    "task_id": task.task_id,
                    "worker": worker,
                    "now": now,
                    "deadline": now + lease_seconds,
                }
                for task in eligible
            ]
        )
        return [self._token(self.state.tasks[task.task_id]) for task in eligible]

    @staticmethod
    def _token(task: Task) -> Lease:
        return Lease(
            task.task_id, task.worker, task.generation, task.deadline, deepcopy(task.payload)
        )

    def ack(self, lease: Lease, *, now: int) -> None:
        self._commit(
            [
                {
                    "op": "ack",
                    "task_id": lease.task_id,
                    "worker": lease.worker,
                    "generation": lease.generation,
                    "now": now,
                }
            ]
        )

    def release(self, lease: Lease, *, now: int, delay: int = 0) -> None:
        integer(now, "now")
        integer(delay, "delay")
        self._commit(
            [
                {
                    "op": "release",
                    "task_id": lease.task_id,
                    "worker": lease.worker,
                    "generation": lease.generation,
                    "now": now,
                    "available_at": now + delay,
                }
            ]
        )

    def compact(self) -> None:
        self.journal.rotate()
        self.hook("compact.rotated")
        self.snapshots.publish(self.sequence, self.state)
        self.journal.discard_sealed()
        self.hook("compact.pruned")

    def inspect(self, task_id: str) -> Task:
        return Task(**deepcopy(asdict(self.state.tasks[task_id])))

    def stats(self) -> dict[str, int]:
        counts = dict.fromkeys(("ready", "leased", "done", "dead"), 0)
        for task in self.state.tasks.values():
            counts[task.status] += 1
        return counts

    def export(self) -> dict:
        return {"sequence": self.sequence, "state": self.state.document()}
