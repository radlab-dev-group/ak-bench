"""The record of a learning session (plan section 17).

A replay must be able to say *which* knowledge it may see. The answer cannot
be "whatever is in the knowledge base now" — that is unrepeatable and
undebuggable. It is a learning session manifest: the tasks whose work wrote
the knowledge, the plugin that wrote it, the collection the plugin was
configured to use, and the digests of all of it.

The manifest digests the facts AK-Bench can observe. It deliberately does not
claim to digest the knowledge base's content: the router offers no readback
(see ``docs/ROUTER_INTEGRATION.md`` section 7), so a content hash would be an
invention presented as evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from akbench.descriptors.registry import compute_digest


@dataclass(frozen=True)
class SessionTask:
    """One task whose execution contributed knowledge to the session."""

    task_uid: str
    task_digest: str
    run_uid: str | None = None
    verdict: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_uid": self.task_uid,
            "task_digest": self.task_digest,
            "run_uid": self.run_uid,
            "verdict": self.verdict,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SessionTask:
        return cls(
            task_uid=str(payload["task_uid"]),
            task_digest=str(payload["task_digest"]),
            run_uid=payload.get("run_uid"),
            verdict=payload.get("verdict"),
        )


@dataclass(frozen=True)
class LearningSession:
    """What one learning run left behind, as far as AK-Bench can observe.

    ``collection_prefix`` is the namespace the plugin was configured with. When
    it is ``None`` the plugin ran on its built-in default, which means the
    session shares a namespace with anything else doing the same — a fact a
    memory experiment has to know, so it is reported, not assumed away.
    """

    session_id: str
    experiment_uid: str
    plugin_id: str
    plugin_version: str
    tasks: list[SessionTask] = field(default_factory=list)
    collection_prefix: str | None = None
    collection_prefix_source: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    notes: str | None = None

    @property
    def digest(self) -> str:
        """Digest of the observable facts of this session."""
        return compute_digest(self._digest_payload())

    @property
    def task_uids(self) -> list[str]:
        return [task.task_uid for task in self.tasks]

    def has_task(self, task_uid: str) -> bool:
        return task_uid in self.task_uids

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "experiment_uid": self.experiment_uid,
            "plugin": {"id": self.plugin_id, "version": self.plugin_version},
            "digest": self.digest,
            "tasks": [task.as_dict() for task in self.tasks],
            "collection_prefix": self.collection_prefix,
            "collection_prefix_source": self.collection_prefix_source,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LearningSession:
        plugin = payload.get("plugin") or {}
        return cls(
            session_id=str(payload["session_id"]),
            experiment_uid=str(payload.get("experiment_uid", "")),
            plugin_id=str(plugin.get("id", "")),
            plugin_version=str(plugin.get("version", "")),
            tasks=[SessionTask.from_dict(task) for task in payload.get("tasks", [])],
            collection_prefix=payload.get("collection_prefix"),
            collection_prefix_source=payload.get("collection_prefix_source"),
            started_at=payload.get("started_at"),
            finished_at=payload.get("finished_at"),
            notes=payload.get("notes"),
        )

    def _digest_payload(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "experiment_uid": self.experiment_uid,
            "plugin": f"{self.plugin_id}@{self.plugin_version}",
            "tasks": [
                {"task_uid": task.task_uid, "task_digest": task.task_digest}
                for task in sorted(self.tasks, key=lambda item: item.task_uid)
            ],
            "collection_prefix": self.collection_prefix,
        }
