"""Content-addressed deterministic package metadata index."""

import hashlib
from collections.abc import Iterable
from pathlib import Path

from .model import Release, canonical, normalize
from .versions import Version


class Repository:
    def __init__(self, releases: Iterable[Release] = ()) -> None:
        self._releases: dict[str, dict[Version, Release]] = {}
        for release in releases:
            self.add(release)

    def add(self, release: Release) -> None:
        versions = self._releases.setdefault(release.name, {})
        if release.version in versions:
            raise ValueError(f"duplicate release {release.name} {release.version}")
        versions[release.version] = release

    def versions(self, name: str) -> tuple[Release, ...]:
        versions = self._releases.get(normalize(name), {})
        return tuple(versions[version] for version in sorted(versions, reverse=True))

    def get(self, name: str, version: str | Version) -> Release:
        version = Version.parse(version) if isinstance(version, str) else version
        return self._releases[normalize(name)][version]

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._releases))

    def all(self) -> tuple[Release, ...]:
        return tuple(release for name in self.names() for release in self.versions(name))

    def document(self) -> dict:
        return {"version": 1, "releases": [release.document() for release in self.all()]}

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical(self.document()).encode()).hexdigest()

    @classmethod
    def load(cls, document: dict) -> "Repository":
        if document.get("version") != 1 or not isinstance(document.get("releases"), list):
            raise ValueError("invalid repository document")
        return cls(Release.load(row) for row in document["releases"])

    @classmethod
    def read(cls, path: Path) -> "Repository":
        import json

        return cls.load(json.loads(Path(path).read_text()))

    def overlay(self, other: "Repository", *, replace: bool = False) -> "Repository":
        releases = {release.identity: release for release in self.all()}
        for release in other.all():
            if release.identity in releases and not replace:
                raise ValueError("repository overlay collision")
            releases[release.identity] = release
        return Repository(releases.values())

    def subset(self, names: Iterable[str]) -> "Repository":
        wanted = {normalize(name) for name in names}
        return Repository(release for release in self.all() if release.name in wanted)
