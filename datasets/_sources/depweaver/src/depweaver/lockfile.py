"""Checksummed, target-bound lockfiles and explicit partial-update requests."""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .markers import Target
from .model import Dependency, Policy, Release, Request, Resolution, canonical, normalize
from .repository import Repository


@dataclass(frozen=True)
class Lockfile:
    resolution: Resolution

    def document(self) -> dict:
        body = {"version": 1, "resolution": self.resolution.document()}
        return {"body": body, "sha256": hashlib.sha256(canonical(body).encode()).hexdigest()}

    @classmethod
    def load(cls, document: dict) -> "Lockfile":
        if not isinstance(document, dict) or set(document) != {"body", "sha256"}:
            raise ValueError("invalid lockfile envelope")
        body = document["body"]
        if hashlib.sha256(canonical(body).encode()).hexdigest() != document["sha256"]:
            raise ValueError("lockfile checksum mismatch")
        if body["version"] != 1:
            raise ValueError("unsupported lockfile version")
        row = body["resolution"]
        selected = tuple(Release.load(release) for release in row["selected"])
        if len({release.name for release in selected}) != len(selected):
            raise ValueError("duplicate locked package")
        if tuple(release.name for release in selected) != tuple(
            sorted(release.name for release in selected)
        ):
            raise ValueError("lockfile packages are not sorted")
        extras = tuple((name, tuple(values)) for name, values in sorted(row["extras"].items()))
        if {name for name, values in extras} != {release.name for release in selected}:
            raise ValueError("lockfile extras/package mismatch")
        for _name, values in extras:
            if tuple(sorted(set(values))) != values or any(
                normalize(value) != value for value in values
            ):
                raise ValueError("noncanonical locked extras")
        for key in ("request", "repository"):
            value = row[key]
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise ValueError("invalid lockfile fingerprint")
        resolution = Resolution(
            selected, extras, Target(**row["target"]), row["request"], row["repository"]
        )
        from .graph import Graph

        Graph.from_resolution(resolution)
        return cls(resolution)

    @classmethod
    def read(cls, path: Path) -> "Lockfile":
        return cls.load(json.loads(Path(path).read_text()))

    def write(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".lock-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w") as stream:
                stream.write(canonical(self.document()) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def request(
        self,
        roots: tuple[Dependency, ...],
        *,
        update: frozenset[str] = frozenset(),
        target: Target | None = None,
        policy: Policy | None = None,
    ) -> Request:
        target = target or self.resolution.target
        if target != self.resolution.target:
            raise ValueError("partial update cannot reuse locks for another target")
        return Request(
            roots,
            target,
            tuple(sorted(self.resolution.versions().items())),
            update,
            policy or Policy(),
        )

    def verify_repository(self, repository: Repository) -> None:
        if repository.fingerprint != self.resolution.repository_fingerprint:
            raise ValueError("repository metadata changed since locking")
        for release in self.resolution.selected:
            actual = repository.get(release.name, release.version)
            if actual.document() != release.document():
                raise ValueError("locked release metadata mismatch")


@dataclass(frozen=True)
class Difference:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    upgraded: tuple[tuple[str, str, str], ...]
    downgraded: tuple[tuple[str, str, str], ...]
    features: tuple[str, ...]


def diff(first: Lockfile, second: Lockfile) -> Difference:
    before = {release.name: release for release in first.resolution.selected}
    after = {release.name: release for release in second.resolution.selected}
    upgraded, downgraded = [], []
    for name in sorted(before.keys() & after.keys()):
        old, new = before[name].version, after[name].version
        if new > old:
            upgraded.append((name, str(old), str(new)))
        elif new < old:
            downgraded.append((name, str(old), str(new)))
    before_extras, after_extras = dict(first.resolution.extras), dict(second.resolution.extras)
    features = tuple(
        name
        for name in sorted(before.keys() & after.keys())
        if before_extras[name] != after_extras[name]
    )
    return Difference(
        tuple(sorted(after.keys() - before.keys())),
        tuple(sorted(before.keys() - after.keys())),
        tuple(upgraded),
        tuple(downgraded),
        features,
    )
