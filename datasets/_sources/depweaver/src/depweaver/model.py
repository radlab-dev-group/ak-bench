"""Canonical immutable package metadata and resolution records."""

import hashlib
import json
import re
from dataclasses import dataclass, field

from .markers import Marker, Target
from .versions import Spec, Version


def normalize(name: str) -> str:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise ValueError("invalid package/extra name")
    return re.sub(r"[-_.]+", "-", name).lower()


def canonical(document: object) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class Dependency:
    name: str
    spec: Spec = field(default_factory=Spec)
    extras: frozenset[str] = frozenset()
    marker: Marker = field(default_factory=Marker)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", normalize(self.name))
        if isinstance(self.spec, str):
            object.__setattr__(self, "spec", Spec.parse(self.spec))
        if isinstance(self.marker, str):
            object.__setattr__(self, "marker", Marker(self.marker))
        object.__setattr__(self, "extras", frozenset(normalize(extra) for extra in self.extras))
        if not isinstance(self.spec, Spec) or not isinstance(self.marker, Marker):
            raise ValueError("invalid dependency spec or marker")

    def document(self) -> dict:
        return {
            "name": self.name,
            "spec": str(self.spec),
            "extras": sorted(self.extras),
            "marker": self.marker.text,
        }

    @classmethod
    def load(cls, document: dict) -> "Dependency":
        if set(document) - {"name", "spec", "extras", "marker"}:
            raise ValueError("unknown dependency fields")
        return cls(**document)


@dataclass(frozen=True)
class Release:
    name: str
    version: Version
    dependencies: tuple[Dependency, ...] = ()
    extras: frozenset[str] = frozenset()
    requires_python: Spec = field(default_factory=Spec)
    yanked: bool = False
    digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", normalize(self.name))
        if isinstance(self.version, str):
            object.__setattr__(self, "version", Version.parse(self.version))
        if isinstance(self.requires_python, str):
            object.__setattr__(self, "requires_python", Spec.parse(self.requires_python))
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        object.__setattr__(self, "extras", frozenset(normalize(extra) for extra in self.extras))
        if not isinstance(self.version, Version) or not isinstance(self.requires_python, Spec):
            raise ValueError("invalid release version or Python constraint")
        if any(not isinstance(dependency, Dependency) for dependency in self.dependencies):
            raise ValueError("invalid release dependency")
        if type(self.yanked) is not bool:
            raise ValueError("yanked must be a boolean")
        if self.digest and not re.fullmatch(r"[a-f0-9]{64}", self.digest):
            raise ValueError("digest must be a SHA-256 hex string")

    @property
    def identity(self) -> tuple[str, str]:
        return self.name, str(self.version.without_build())

    def document(self) -> dict:
        return {
            "name": self.name,
            "version": str(self.version),
            "dependencies": [dependency.document() for dependency in self.dependencies],
            "extras": sorted(self.extras),
            "requires_python": str(self.requires_python),
            "yanked": self.yanked,
            "digest": self.digest,
        }

    @classmethod
    def load(cls, document: dict) -> "Release":
        document = document.copy()
        document["dependencies"] = tuple(
            Dependency.load(row) for row in document.get("dependencies", [])
        )
        return cls(**document)


@dataclass(frozen=True)
class Constraint:
    dependency: Dependency
    parent: tuple[str, str] | None

    @property
    def fingerprint(self) -> str:
        return canonical({"dependency": self.dependency.document(), "parent": self.parent})


@dataclass(frozen=True)
class Policy:
    allow_prerelease: bool = False
    allow_yanked: bool = False
    prefer_lowest: bool = False
    max_decisions: int = 100_000

    def document(self) -> dict:
        return {
            "allow_prerelease": self.allow_prerelease,
            "allow_yanked": self.allow_yanked,
            "prefer_lowest": self.prefer_lowest,
            "max_decisions": self.max_decisions,
        }


@dataclass(frozen=True)
class Request:
    roots: tuple[Dependency, ...]
    target: Target = field(default_factory=Target)
    locked: tuple[tuple[str, str], ...] = ()
    update: frozenset[str] = frozenset()
    policy: Policy = field(default_factory=Policy)

    def __post_init__(self) -> None:
        object.__setattr__(self, "roots", tuple(self.roots))
        pins = tuple(
            sorted((normalize(name), str(Version.parse(version))) for name, version in self.locked)
        )
        if len({name for name, version in pins}) != len(pins):
            raise ValueError("duplicate locked package")
        object.__setattr__(self, "locked", pins)
        object.__setattr__(self, "update", frozenset(normalize(name) for name in self.update))
        if any(not isinstance(root, Dependency) for root in self.roots):
            raise ValueError("roots must be dependencies")
        if type(self.policy.max_decisions) is not int or self.policy.max_decisions < 1:
            raise ValueError("max_decisions must be positive")

    def document(self) -> dict:
        return {
            "roots": sorted((root.document() for root in self.roots), key=canonical),
            "target": self.target.document(),
            "locked": dict(self.locked),
            "update": sorted(self.update),
            "policy": self.policy.document(),
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical(self.document()).encode()).hexdigest()


@dataclass(frozen=True)
class Resolution:
    selected: tuple[Release, ...]
    extras: tuple[tuple[str, tuple[str, ...]], ...]
    target: Target
    request_fingerprint: str
    repository_fingerprint: str

    def versions(self) -> dict[str, str]:
        return {release.name: str(release.version) for release in self.selected}

    def document(self) -> dict:
        return {
            "selected": [release.document() for release in self.selected],
            "extras": {name: list(extras) for name, extras in self.extras},
            "target": self.target.document(),
            "request": self.request_fingerprint,
            "repository": self.repository_fingerprint,
        }
