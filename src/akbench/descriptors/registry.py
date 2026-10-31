"""Descriptor registry: loading, versioned identity, snapshots (plan section 9).

Identity is ``(kind, id, version)``. The same ``id`` may exist in several
versions, and every registration records a content digest: an experiment stores
the digests of the descriptors it used, so editing a descriptor can never
silently reinterpret earlier results.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from akbench.core.errors import DescriptorError
from akbench.descriptors.agent import AgentDescriptor
from akbench.descriptors.category import CategoryDescriptor
from akbench.descriptors.dimension import DimensionDescriptor
from akbench.descriptors.evaluator import EvaluatorDescriptor
from akbench.descriptors.metric import MetricDescriptor
from akbench.descriptors.model import ModelDescriptor
from akbench.descriptors.plugin import PluginDescriptor
from akbench.descriptors.runtime import RuntimeDescriptor

CONFIG_SUFFIXES = (".yaml", ".yml")


class DescriptorKind(StrEnum):
    AGENT = "agent"
    RUNTIME = "runtime"
    PLUGIN = "plugin"
    MODEL = "model"
    CATEGORY = "category"
    EVALUATOR = "evaluator"
    DIMENSION = "dimension"
    METRIC = "metric"


DESCRIPTOR_MODELS: dict[DescriptorKind, type[BaseModel]] = {
    DescriptorKind.AGENT: AgentDescriptor,
    DescriptorKind.RUNTIME: RuntimeDescriptor,
    DescriptorKind.PLUGIN: PluginDescriptor,
    DescriptorKind.MODEL: ModelDescriptor,
    DescriptorKind.CATEGORY: CategoryDescriptor,
    DescriptorKind.EVALUATOR: EvaluatorDescriptor,
    DescriptorKind.DIMENSION: DimensionDescriptor,
    DescriptorKind.METRIC: MetricDescriptor,
}


def canonical_json(payload: Any) -> str:
    """Deterministic JSON used for digests, so hashes survive round-trips."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_digest(payload: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest()}"


def _version_key(version: str) -> tuple[tuple[int, ...], str]:
    """Sort semver-ish strings numerically; fall back to lexicographic order."""
    parts = tuple(int(part) for part in re.findall(r"\d+", version))
    return (parts, version)


@dataclass(frozen=True)
class DescriptorSnapshot:
    """What an experiment needs to pin a descriptor for reproducibility."""

    kind: DescriptorKind
    id: str
    version: str
    digest: str
    payload: dict[str, Any]
    source: str | None = None

    @property
    def identity(self) -> str:
        return f"{self.kind.value}:{self.id}@{self.version}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "id": self.id,
            "version": self.version,
            "digest": self.digest,
            "source": self.source,
        }


@dataclass(frozen=True)
class LoadedDescriptor:
    kind: DescriptorKind
    descriptor: BaseModel
    snapshot: DescriptorSnapshot
    source: Path | None = None

    @property
    def identity(self) -> str:
        return self.snapshot.identity


class DescriptorRegistry:
    """In-memory store of validated descriptors, keyed by kind/id/version."""

    def __init__(self, models: dict[DescriptorKind, type[BaseModel]] | None = None) -> None:
        self._models = dict(DESCRIPTOR_MODELS if models is None else models)
        self._entries: dict[tuple[DescriptorKind, str, str], LoadedDescriptor] = {}

    def register_model(self, kind: DescriptorKind, model: type[BaseModel]) -> None:
        self._models[DescriptorKind(kind)] = model

    def model_for(self, kind: DescriptorKind) -> type[BaseModel]:
        kind = DescriptorKind(kind)
        if kind not in self._models:
            raise DescriptorError(f"no descriptor model registered for kind {kind.value!r}")
        return self._models[kind]

    def add(
        self, descriptor: BaseModel, kind: DescriptorKind, source: Path | None = None
    ) -> LoadedDescriptor:
        """Register an already-validated descriptor instance."""
        kind = DescriptorKind(kind)
        identity_fields = _identity_from(descriptor)
        return self._store(
            kind=kind,
            descriptor=descriptor,
            descriptor_id=identity_fields[0],
            version=identity_fields[1],
            payload=descriptor.model_dump(mode="json"),
            source=source,
        )

    def add_raw(
        self,
        kind: DescriptorKind,
        data: dict[str, Any],
        source: Path | None = None,
    ) -> LoadedDescriptor:
        """Validate a raw mapping against the kind's model and register it."""
        kind = DescriptorKind(kind)
        model = self.model_for(kind)
        try:
            descriptor = model.model_validate(data)
        except ValidationError as exc:
            location = str(source) if source else f"{kind.value}:<memory>"
            raise DescriptorError(
                f"invalid {kind.value} descriptor in {location}: {_render(exc)}"
            ) from exc
        return self.add(descriptor, kind, source=source)

    def _store(
        self,
        kind: DescriptorKind,
        descriptor: BaseModel,
        descriptor_id: str,
        version: str,
        payload: dict[str, Any],
        source: Path | None,
    ) -> LoadedDescriptor:
        digest = compute_digest(payload)
        key = (kind, descriptor_id, version)
        existing = self._entries.get(key)
        if existing is not None:
            if existing.snapshot.digest == digest:
                return existing  # identical content re-registered: idempotent
            raise DescriptorError(
                f"conflicting {kind.value} descriptor {descriptor_id}@{version}: "
                f"already registered with digest {existing.snapshot.digest[:19]}... "
                f"from {existing.source or '<memory>'}, "
                f"new digest {digest[:19]}... from {source or '<memory>'}"
            )
        snapshot = DescriptorSnapshot(
            kind=kind,
            id=descriptor_id,
            version=version,
            digest=digest,
            payload=payload,
            source=str(source) if source else None,
        )
        loaded = LoadedDescriptor(
            kind=kind, descriptor=descriptor, snapshot=snapshot, source=source
        )
        self._entries[key] = loaded
        return loaded

    def get(
        self, kind: DescriptorKind, descriptor_id: str, version: str | None = None
    ) -> LoadedDescriptor | None:
        """Resolve ``id`` (newest version) or an exact ``id@version``."""
        kind = DescriptorKind(kind)
        if version is None and "@" in descriptor_id:
            descriptor_id, version = descriptor_id.split("@", 1)
        if version is not None:
            return self._entries.get((kind, descriptor_id, version))
        matches = self.versions(kind, descriptor_id)
        if not matches:
            return None
        newest = sorted(matches, key=_version_key)[-1]
        return self._entries[(kind, descriptor_id, newest)]

    def require(
        self, kind: DescriptorKind, descriptor_id: str, version: str | None = None
    ) -> LoadedDescriptor:
        found = self.get(kind, descriptor_id, version)
        if found is None:
            known = ", ".join(self.ids(kind)) or "none registered"
            wanted = descriptor_id if version is None else f"{descriptor_id}@{version}"
            raise DescriptorError(
                f"unknown {DescriptorKind(kind).value} descriptor {wanted!r}; registered: {known}"
            )
        return found

    def versions(self, kind: DescriptorKind, descriptor_id: str) -> list[str]:
        kind = DescriptorKind(kind)
        return [key[2] for key in self._entries if key[0] == kind and key[1] == descriptor_id]

    def ids(self, kind: DescriptorKind) -> list[str]:
        kind = DescriptorKind(kind)
        return sorted({key[1] for key in self._entries if key[0] == kind})

    def kinds(self) -> list[DescriptorKind]:
        return sorted({key[0] for key in self._entries}, key=lambda kind: kind.value)

    def entries(self, kind: DescriptorKind | None = None) -> list[LoadedDescriptor]:
        wanted = None if kind is None else DescriptorKind(kind)
        found = [
            entry
            for key, entry in self._entries.items()
            if wanted is None or key[0] == wanted
        ]
        return sorted(
            found,
            key=lambda entry: (entry.kind.value, entry.snapshot.id, entry.snapshot.version),
        )

    def snapshots(self, kind: DescriptorKind | None = None) -> list[DescriptorSnapshot]:
        return [entry.snapshot for entry in self.entries(kind)]

    def digest_map(self, kind: DescriptorKind | None = None) -> dict[str, str]:
        """``kind:id@version -> digest`` for embedding in an experiment record."""
        return {snapshot.identity: snapshot.digest for snapshot in self.snapshots(kind)}

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: tuple[DescriptorKind, str, str]) -> bool:
        kind, descriptor_id, version = key
        return (DescriptorKind(kind), descriptor_id, version) in self._entries


def _identity_from(descriptor: BaseModel) -> tuple[str, str]:
    try:
        return str(descriptor.id), str(descriptor.version)  # type: ignore[attr-defined]
    except AttributeError as exc:  # pragma: no cover - guarded by the models
        raise DescriptorError(f"descriptor model is missing id/version: {type(exc)}") from exc


def _render(exc: ValidationError) -> str:
    parts = []
    for issue in exc.errors():
        location = ".".join(str(part) for part in issue["loc"]) or "<root>"
        parts.append(f"{location}: {issue['msg']}")
    return "; ".join(parts)


def load_descriptor_file(
    path: Path,
    kind: DescriptorKind,
    registry: DescriptorRegistry | None = None,
) -> DescriptorRegistry:
    """Validate a single descriptor file, independently of the rest of a directory.

    Validation reports per file, so one broken descriptor cannot hide the
    verdict on its neighbours.
    """
    target = registry or DescriptorRegistry()
    for document in _read_yaml_documents(Path(path)):
        target.add_raw(DescriptorKind(kind), document, source=Path(path))
    return target


def iter_descriptor_files(
    root: Path, kinds: Iterable[DescriptorKind] | None = None
) -> list[tuple[DescriptorKind, Path]]:
    """Map ``<root>/<kind-dir>/*.yaml`` files to kinds.

    The directory name selects the kind, so adding a component never means
    touching engine code.
    """
    wanted = {DescriptorKind(kind) for kind in kinds} if kinds else set(DescriptorKind)
    directory = Path(root)
    found: list[tuple[DescriptorKind, Path]] = []
    for kind in sorted(wanted, key=lambda item: item.value):
        kind_dir = directory / _kind_directory(kind)
        if not kind_dir.is_dir():
            continue
        for path in sorted(kind_dir.glob("*")):
            if path.suffix.lower() in CONFIG_SUFFIXES and path.is_file():
                found.append((kind, path))
    return found


def _kind_directory(kind: DescriptorKind) -> str:
    """Directory naming: ``agent`` -> ``agents``, ``metric`` -> ``metrics``."""
    irregular = {
        DescriptorKind.CATEGORY: "categories",
        DescriptorKind.EVALUATOR: "evaluators",
        DescriptorKind.MODEL: "models",
    }
    return irregular.get(kind, f"{kind.value}s")


def load_registry(
    root: Path,
    kinds: Iterable[DescriptorKind] | None = None,
    registry: DescriptorRegistry | None = None,
) -> DescriptorRegistry:
    """Load and validate every descriptor under ``root``."""
    target = registry or DescriptorRegistry()
    directory = Path(root)
    if not directory.exists():
        raise DescriptorError(f"descriptor directory not found: {directory}")
    for kind, path in iter_descriptor_files(directory, kinds):
        for document in _read_yaml_documents(path):
            target.add_raw(kind, document, source=path)
    return target


def _read_yaml_documents(path: Path) -> list[dict[str, Any]]:
    """Read one descriptor file.

    Three shapes are accepted so descriptor authors are not forced into a
    single style: one mapping, a list of mappings, or a multi-document stream.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DescriptorError(f"cannot read descriptor {path}: {exc}") from exc

    try:
        documents = list(yaml.safe_load_all(raw))
    except yaml.YAMLError as exc:
        raise DescriptorError(f"invalid YAML in {path}: {exc}") from exc

    collected: list[dict[str, Any]] = []
    for doc_index, document in enumerate(documents):
        if document is None:
            continue
        if isinstance(document, dict):
            collected.append(document)
            continue
        if isinstance(document, list):
            for index, item in enumerate(document):
                if not isinstance(item, dict):
                    raise DescriptorError(
                        f"{path} document {doc_index} entry {index}: expected a mapping"
                    )
                collected.append(item)
            continue
        raise DescriptorError(f"{path} document {doc_index}: descriptor root must be a mapping")
    if not collected:
        raise DescriptorError(f"{path}: no descriptor document found")
    return collected
