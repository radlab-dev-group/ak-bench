"""Reproducible software inventory export and metadata-bound import."""

import hashlib
from dataclasses import dataclass
from urllib.parse import quote, unquote

from .codec import envelope, unwrap
from .graph import Graph
from .model import Release, Resolution, canonical, normalize
from .repository import Repository
from .versions import Version


def package_url(name: str, version: str) -> str:
    return (
        "pkg:depweaver/"
        + quote(normalize(name), safe="")
        + "@"
        + quote(str(Version.parse(version)), safe="")
    )


def parse_url(value: str) -> tuple[str, str]:
    prefix = "pkg:depweaver/"
    if not value.startswith(prefix) or value.count("@") != 1:
        raise ValueError("invalid package URL")
    name, version = value[len(prefix) :].split("@")
    identity = normalize(unquote(name)), str(Version.parse(unquote(version)))
    if package_url(*identity) != value:
        raise ValueError("noncanonical package URL")
    return identity


@dataclass(frozen=True)
class Component:
    release: Release
    extras: tuple[str, ...]

    @property
    def reference(self) -> str:
        return package_url(self.release.name, str(self.release.version))

    def document(self) -> dict:
        return {
            "reference": self.reference,
            "metadata": self.release.document(),
            "extras": list(self.extras),
        }


@dataclass(frozen=True)
class Inventory:
    components: tuple[Component, ...]
    edges: tuple[tuple[str, str], ...]
    target: tuple[tuple[str, str], ...]
    repository: str

    def document(self) -> dict:
        return envelope(
            "inventory",
            {
                "components": [component.document() for component in self.components],
                "edges": [list(edge) for edge in self.edges],
                "target": dict(self.target),
                "repository": self.repository,
            },
        )

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical(self.document()).encode()).hexdigest()

    @classmethod
    def from_resolution(cls, resolution: Resolution) -> "Inventory":
        extras = dict(resolution.extras)
        components = tuple(
            Component(release, extras[release.name]) for release in resolution.selected
        )
        references = {component.release.name: component.reference for component in components}
        graph = Graph.from_resolution(resolution)
        edges = tuple(
            sorted({(references[edge.parent], references[edge.child]) for edge in graph.edges})
        )
        return cls(
            components,
            edges,
            tuple(sorted(resolution.target.document().items())),
            resolution.repository_fingerprint,
        )

    @classmethod
    def load(cls, document: dict, repository: Repository | None = None) -> "Inventory":
        from .markers import Target

        payload = unwrap(document, "inventory")
        if not isinstance(payload, dict) or set(payload) != {
            "components",
            "edges",
            "target",
            "repository",
        }:
            raise ValueError("invalid inventory fields")
        components = []
        for row in payload["components"]:
            if set(row) != {"reference", "metadata", "extras"}:
                raise ValueError("invalid inventory component fields")
            release = Release.load(row["metadata"])
            if parse_url(row["reference"]) != (release.name, str(release.version)):
                raise ValueError("component identity mismatch")
            extras = row["extras"]
            if (
                not isinstance(extras, list)
                or extras != sorted(set(extras))
                or not set(extras) <= release.extras
            ):
                raise ValueError("invalid component extras")
            components.append(Component(release, tuple(extras)))
        names = [component.release.name for component in components]
        if names != sorted(set(names)):
            raise ValueError("inventory components are not distinct and sorted")
        references = {component.reference for component in components}
        edges = []
        for edge in payload["edges"]:
            if (
                not isinstance(edge, list)
                or len(edge) != 2
                or any(value not in references for value in edge)
            ):
                raise ValueError("invalid inventory edge")
            edges.append(tuple(edge))
        if edges != sorted(set(edges)):
            raise ValueError("inventory edges are not distinct and sorted")
        target = Target(**payload["target"])
        resolution = Resolution(
            tuple(component.release for component in components),
            tuple((component.release.name, component.extras) for component in components),
            target,
            "0" * 64,
            payload["repository"],
        )
        actual = cls.from_resolution(resolution)
        if actual.edges != tuple(edges):
            raise ValueError("inventory edges differ from active dependency metadata")
        if repository is not None:
            if repository.fingerprint != actual.repository:
                raise ValueError("inventory repository fingerprint mismatch")
            for component in actual.components:
                if (
                    repository.get(component.release.name, component.release.version)
                    != component.release
                ):
                    raise ValueError("inventory component differs from repository metadata")
        return actual

    def compare(self, other: "Inventory") -> dict:
        before = {component.release.name: component for component in self.components}
        after = {component.release.name: component for component in other.components}
        return {
            "added": sorted(after.keys() - before.keys()),
            "removed": sorted(before.keys() - after.keys()),
            "changed": sorted(
                name for name in before.keys() & after.keys() if before[name] != after[name]
            ),
            "target_changed": self.target != other.target,
            "repository_changed": self.repository != other.repository,
        }

    def verify_digests(self, blobs: dict[str, bytes]) -> tuple[str, ...]:
        missing = []
        for component in self.components:
            expected = component.release.digest
            blob = blobs.get(component.reference)
            if not expected or blob is None:
                missing.append(component.reference)
            elif hashlib.sha256(blob).hexdigest() != expected:
                raise ValueError("artifact digest mismatch: " + component.reference)
        return tuple(missing)
