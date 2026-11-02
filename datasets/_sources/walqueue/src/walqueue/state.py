"""Pure queue state transitions shared by live transactions and WAL replay."""

from copy import deepcopy
from dataclasses import asdict, replace

from .codec import canonical
from .errors import CorruptStore, KeyConflict, StaleLease
from .model import Task, integer, name


class State:
    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self.keys: dict[str, dict] = {}

    def clone(self) -> "State":
        return self.restore(self.document())

    def apply(self, commands: list[dict]) -> None:
        for command in commands:
            operation = command["op"]
            if operation == "put":
                self._put(command)
            elif operation == "lease":
                self._lease(command)
            elif operation == "ack":
                self._ack(command)
            elif operation == "release":
                self._release(command)
            elif operation == "expire":
                self._expire(command)
            else:
                raise ValueError("unknown state operation")

    def _put(self, command: dict) -> None:
        task_id = name(command["task_id"], "task id")
        key = name(command["key"], "idempotency key")
        payload = command["payload"]
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        payload = deepcopy(payload)
        canonical(payload)
        available_at = integer(command["available_at"], "available_at")
        max_attempts = integer(command["max_attempts"], "max_attempts", 1)
        identity = {
            "task_id": task_id,
            "payload": payload,
            "available_at": available_at,
            "max_attempts": max_attempts,
        }
        if key in self.keys:
            if self.keys[key] != identity:
                raise KeyConflict("idempotency key belongs to another request")
            return
        if task_id in self.tasks:
            raise KeyConflict("task id already exists")
        self.keys[key] = identity
        self.tasks[task_id] = Task(task_id, payload, available_at, max_attempts)

    def _lease(self, command: dict) -> None:
        task = self.tasks[command["task_id"]]
        now = integer(command["now"], "now")
        deadline = integer(command["deadline"], "deadline")
        worker = name(command["worker"], "worker")
        if task.status != "ready" or task.available_at > now or deadline <= now:
            raise ValueError("task is not leasable")
        if task.attempts >= task.max_attempts:
            raise ValueError("task has exhausted attempts")
        self.tasks[task.task_id] = replace(
            task,
            status="leased",
            attempts=task.attempts + 1,
            generation=task.generation + 1,
            worker=worker,
            deadline=deadline,
        )

    def validate_token(self, task_id: str, worker: str, generation: int, now: int) -> Task:
        integer(now, "now")
        integer(generation, "generation", 1)
        task = self.tasks.get(task_id)
        if (
            task is None
            or task.status != "leased"
            or task.worker != worker
            or (task.generation != generation or task.deadline <= now)
        ):
            raise StaleLease("lease is stale, expired, or belongs to another worker")
        return task

    def _ack(self, command: dict) -> None:
        task = self.validate_token(
            command["task_id"], command["worker"], command["generation"], command["now"]
        )
        self.tasks[task.task_id] = replace(task, status="done", worker=None, deadline=None)

    def _release(self, command: dict) -> None:
        task = self.validate_token(
            command["task_id"], command["worker"], command["generation"], command["now"]
        )
        available_at = integer(command["available_at"], "available_at")
        if available_at < command["now"]:
            raise ValueError("release cannot schedule in the past")
        status = "dead" if task.attempts >= task.max_attempts else "ready"
        self.tasks[task.task_id] = replace(
            task,
            status=status,
            available_at=available_at,
            worker=None,
            deadline=None,
        )

    def _expire(self, command: dict) -> None:
        task = self.tasks[command["task_id"]]
        now = integer(command["now"], "now")
        if task.status != "leased" or task.deadline > now:
            raise ValueError("lease has not expired")
        status = "dead" if task.attempts >= task.max_attempts else "ready"
        self.tasks[task.task_id] = replace(
            task,
            status=status,
            available_at=task.deadline,
            worker=None,
            deadline=None,
        )

    def document(self) -> dict:
        return {
            "tasks": [asdict(self.tasks[key]) for key in sorted(self.tasks)],
            "keys": deepcopy(dict(sorted(self.keys.items()))),
        }

    @classmethod
    def restore(cls, document: dict) -> "State":
        state = cls()
        try:
            for row in document["tasks"]:
                task = Task(**deepcopy(row))
                name(task.task_id, "task id")
                integer(task.available_at, "available_at")
                integer(task.max_attempts, "max_attempts", 1)
                integer(task.attempts, "attempts")
                integer(task.generation, "generation")
                if task.task_id in state.tasks or task.status not in {
                    "ready",
                    "leased",
                    "done",
                    "dead",
                }:
                    raise ValueError("duplicate task or invalid status")
                if not isinstance(task.payload, dict) or task.attempts > task.max_attempts:
                    raise ValueError("invalid task payload or attempts")
                if task.generation != task.attempts:
                    raise ValueError("generation does not fence every lease")
                if task.status == "leased":
                    name(task.worker, "worker")
                    integer(task.deadline, "deadline", 1)
                elif task.worker is not None or task.deadline is not None:
                    raise ValueError("unleased task retains a lease")
                if task.status == "ready" and task.attempts >= task.max_attempts:
                    raise ValueError("exhausted task is ready")
                state.tasks[task.task_id] = task
            state.keys = deepcopy(document["keys"])
            if not isinstance(state.keys, dict):
                raise ValueError("invalid idempotency table")
            mapped = set()
            for key, identity in state.keys.items():
                name(key, "idempotency key")
                task = state.tasks[identity["task_id"]]
                if (
                    identity["payload"] != task.payload
                    or identity["max_attempts"] != task.max_attempts
                ):
                    raise ValueError("idempotency identity mismatch")
                integer(identity["available_at"], "original available_at")
                if task.task_id in mapped:
                    raise ValueError("multiple keys for a task")
                mapped.add(task.task_id)
            if mapped != set(state.tasks):
                raise ValueError("task without idempotency key")
            canonical(state.document())
        except (KeyError, TypeError, ValueError) as error:
            raise CorruptStore("invalid snapshot state") from error
        return state
