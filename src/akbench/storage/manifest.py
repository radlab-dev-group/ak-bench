"""The reproducibility manifest of one run (plan section 14).

Every run carries the identity of what it was: the experiment and variant, the
agent and adapter, the runtime, the plugin versions, the task and its commit,
the configuration hash, the sandbox image and the execution parameters. With
those, a result can be re-created or refuted later; without them it is an
anecdote.

Unknown fields stay ``None`` and are listed in ``unknown_fields``. A manifest
that quietly filled in a plausible image name or agent version would be worse
than an incomplete one: the reader could not tell a recorded fact from a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from akbench.descriptors.registry import compute_digest

#: The fields plan section 14 requires, in the order a reader checks them.
REQUIRED_FIELDS: tuple[str, ...] = (
    "experiment_uid",
    "variant_uid",
    "task_uid",
    "task_version",
    "repository_commit",
    "agent_id",
    "agent_version",
    "adapter_id",
    "config_hash",
)


@dataclass(frozen=True)
class ReproducibilityManifest:
    """What one run was, in the fields a reproduction needs."""

    experiment_uid: str | None = None
    variant_uid: str | None = None
    run_uid: str | None = None
    task_uid: str | None = None
    task_version: str | None = None
    task_digest: str | None = None
    repository_source: str | None = None
    repository_commit: str | None = None
    agent_id: str | None = None
    agent_version: str | None = None
    adapter_id: str | None = None
    runtime_id: str | None = None
    runtime_lifecycle: str | None = None
    plugin_versions: dict[str, str] = field(default_factory=dict)
    descriptor_digests: dict[str, str] = field(default_factory=dict)
    config_hash: str | None = None
    sandbox_image: str | None = None
    execution_parameters: dict[str, Any] = field(default_factory=dict)
    notes: str | None = None

    @property
    def digest(self) -> str:
        """Digest of the identity facts, so a run can cite its manifest."""
        return compute_digest(self._identity())

    @property
    def unknown_fields(self) -> list[str]:
        """Fields the run could not state, plan fields first.

        A plugin with no recorded version and a plugin that reported none look
        the same in ``plugin_versions`` and in this list — which is the point:
        an absent fact is reported, not hidden.
        """
        missing = [name for name in REQUIRED_FIELDS if getattr(self, name, None) is None]
        if not self.plugin_versions:
            missing.append("plugin_versions")
        if not self.descriptor_digests:
            missing.append("descriptor_digests")
        if self.sandbox_image is None:
            missing.append("sandbox_image")
        return missing

    @property
    def complete(self) -> bool:
        """True when every required field is stated.

        An ad-hoc run outside an experiment is legitimately incomplete; a
        planned one is not, and the caller decides which warning to raise.
        """
        return not [name for name in REQUIRED_FIELDS if getattr(self, name, None) is None]

    def _identity(self) -> dict[str, Any]:
        return {
            "experiment_uid": self.experiment_uid,
            "variant_uid": self.variant_uid,
            "task_uid": self.task_uid,
            "task_digest": self.task_digest,
            "repository_commit": self.repository_commit,
            "agent": f"{self.agent_id}@{self.agent_version}",
            "adapter_id": self.adapter_id,
            "runtime": self.runtime_id,
            "plugin_versions": dict(sorted(self.plugin_versions.items())),
            "descriptor_digests": dict(sorted(self.descriptor_digests.items())),
            "config_hash": self.config_hash,
            "sandbox_image": self.sandbox_image,
            "execution_parameters": self.execution_parameters,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "digest": self.digest,
            "complete": self.complete,
            "unknown_fields": self.unknown_fields,
            "experiment_uid": self.experiment_uid,
            "variant_uid": self.variant_uid,
            "run_uid": self.run_uid,
            "task": {
                "uid": self.task_uid,
                "version": self.task_version,
                "digest": self.task_digest,
            },
            "repository": {"source": self.repository_source, "commit": self.repository_commit},
            "agent": {
                "id": self.agent_id,
                "version": self.agent_version,
                "adapter": self.adapter_id,
            },
            "runtime": {"id": self.runtime_id, "lifecycle": self.runtime_lifecycle},
            "plugin_versions": dict(sorted(self.plugin_versions.items())),
            "descriptor_digests": dict(sorted(self.descriptor_digests.items())),
            "config_hash": self.config_hash,
            "sandbox_image": self.sandbox_image,
            "execution_parameters": dict(self.execution_parameters),
            "notes": self.notes,
        }


def build_manifest(
    run_record: dict[str, Any],
    *,
    experiment_uid: str | None = None,
    variant_uid: str | None = None,
    task: Any | None = None,
    adapter_id: str | None = None,
    runtime_lifecycle: str | None = None,
    plugin_versions: dict[str, str] | None = None,
    descriptor_digests: dict[str, str] | None = None,
    config_hash: str | None = None,
    sandbox_image: str | None = None,
    execution_parameters: dict[str, Any] | None = None,
    notes: str | None = None,
) -> ReproducibilityManifest:
    """Assemble the manifest of one run from what is actually known.

    ``task`` is a :class:`~akbench.datasets.LoadedTask` when the caller has
    one; its digests win over anything in the run record, because the dataset
    layer resolved them from the real task definition.
    """
    task_uid = run_record.get("task_uid")
    task_version: str | None = None
    task_digest: str | None = None
    repository_source: str | None = None
    repository_commit: str | None = None

    if task is not None:
        task_uid = getattr(task, "uid", task_uid)
        task_digest = str(getattr(task, "digest", "")) or None
        # ``task.task`` is the TaskDescriptor; its own ``task`` is the body
        # that carries the repository. Version lives on the descriptor.
        descriptor = getattr(task, "task", None)
        if descriptor is not None:
            task_version = str(getattr(descriptor, "version", "")) or None
            body = getattr(descriptor, "task", descriptor)
            repository = getattr(body, "repository", None)
            if repository is not None:
                repository_source = getattr(repository, "source", None)
                repository_commit = getattr(repository, "ref", None)

    return ReproducibilityManifest(
        experiment_uid=experiment_uid,
        variant_uid=variant_uid,
        run_uid=run_record.get("run_uid"),
        task_uid=task_uid,
        task_version=task_version,
        task_digest=task_digest,
        repository_source=repository_source,
        repository_commit=repository_commit,
        agent_id=run_record.get("agent_id"),
        agent_version=run_record.get("agent_version"),
        adapter_id=adapter_id,
        runtime_id=run_record.get("runtime_id"),
        runtime_lifecycle=runtime_lifecycle,
        plugin_versions=dict(plugin_versions or {}),
        descriptor_digests=dict(descriptor_digests or {}),
        config_hash=config_hash or run_record.get("config_hash"),
        sandbox_image=sandbox_image,
        execution_parameters=dict(execution_parameters or {}),
        notes=notes,
    )
