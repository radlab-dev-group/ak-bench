"""Immutable metadata snapshots, revision checked editing and structural checks."""

from dataclasses import dataclass, replace

from .markers import Target
from .model import Dependency, Release, normalize
from .repository import Repository
from .versions import Version


@dataclass(frozen=True)
class Issue:
    code: str
    package: str
    version: str
    dependency: str

    def document(self) -> dict:
        return {
            "code": self.code,
            "package": self.package,
            "version": self.version,
            "dependency": self.dependency,
        }


def inspect(repository: Repository, target: Target | None = None) -> tuple[Issue, ...]:
    issues = []
    for release in repository.all():
        seen = set()
        for dependency in release.dependencies:
            identity = (
                dependency.name,
                str(dependency.spec),
                dependency.marker.text,
                dependency.extras,
            )
            if identity in seen:
                issues.append(
                    Issue("duplicate-edge", release.name, str(release.version), dependency.name)
                )
            seen.add(identity)
            if target is not None and not dependency.marker.matches(target, release.extras):
                continue
            candidates = repository.versions(dependency.name)
            if not candidates:
                code = "absent-package"
            elif not any(dependency.spec.matches(candidate.version) for candidate in candidates):
                code = "empty-range"
            elif not any(
                dependency.spec.matches(candidate.version) and dependency.extras <= candidate.extras
                for candidate in candidates
            ):
                code = "unknown-extra"
            else:
                continue
            issues.append(Issue(code, release.name, str(release.version), dependency.name))
    return tuple(
        sorted(issues, key=lambda item: (item.package, item.version, item.dependency, item.code))
    )


@dataclass(frozen=True)
class Change:
    name: str
    version: str
    before: Release | None
    after: Release | None

    def inverse(self) -> "Change":
        return Change(self.name, self.version, self.after, self.before)

    def document(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "before": self.before.document() if self.before else None,
            "after": self.after.document() if self.after else None,
        }


@dataclass(frozen=True)
class Revision:
    base: str
    result: str
    changes: tuple[Change, ...]

    def apply(self, repository: Repository) -> Repository:
        if repository.fingerprint != self.base:
            raise ValueError("metadata revision has a stale base")
        rows = {release.identity: release for release in repository.all()}
        touched = set()
        for change in self.changes:
            identity = normalize(change.name), str(Version.parse(change.version).without_build())
            if identity in touched:
                raise ValueError("release changed twice in one revision")
            touched.add(identity)
            if rows.get(identity) != change.before:
                raise ValueError("metadata revision precondition failed")
            if change.after is None:
                if change.before is None:
                    raise ValueError("cannot delete a missing release")
                del rows[identity]
            else:
                if change.after.identity != identity:
                    raise ValueError("metadata edit changes release identity")
                rows[identity] = change.after
        result = Repository(rows.values())
        if result.fingerprint != self.result:
            raise ValueError("metadata revision result fingerprint mismatch")
        return result

    def inverse(self) -> "Revision":
        return Revision(
            self.result, self.base, tuple(change.inverse() for change in reversed(self.changes))
        )

    def document(self) -> dict:
        return {
            "version": 1,
            "base": self.base,
            "result": self.result,
            "changes": [change.document() for change in self.changes],
        }

    @classmethod
    def load(cls, document: dict) -> "Revision":
        if set(document) != {"version", "base", "result", "changes"} or document["version"] != 1:
            raise ValueError("invalid metadata revision")
        changes = []
        for row in document["changes"]:
            changes.append(
                Change(
                    row["name"],
                    row["version"],
                    Release.load(row["before"]) if row["before"] is not None else None,
                    Release.load(row["after"]) if row["after"] is not None else None,
                )
            )
        return cls(document["base"], document["result"], tuple(changes))


class Editor:
    def __init__(self, repository: Repository) -> None:
        self.base = Repository(repository.all())
        self.rows = {release.identity: release for release in repository.all()}

    def put(self, release: Release, *, replace_existing: bool = False) -> None:
        if release.identity in self.rows and not replace_existing:
            raise ValueError("release already exists")
        self.rows[release.identity] = release

    def remove(self, name: str, version: str) -> None:
        del self.rows[(normalize(name), str(Version.parse(version).without_build()))]

    def yank(self, name: str, version: str, value: bool = True) -> None:
        if type(value) is not bool:
            raise ValueError("yank flag must be boolean")
        identity = normalize(name), str(Version.parse(version).without_build())
        self.rows[identity] = replace(self.rows[identity], yanked=value)

    def dependencies(self, name: str, version: str, values: tuple[Dependency, ...]) -> None:
        identity = normalize(name), str(Version.parse(version).without_build())
        self.rows[identity] = replace(self.rows[identity], dependencies=values)

    def preview(self) -> Repository:
        return Repository(self.rows.values())

    def commit(self) -> Revision:
        before = {release.identity: release for release in self.base.all()}
        changes = tuple(
            Change(name, version, before.get((name, version)), self.rows.get((name, version)))
            for name, version in sorted(before.keys() | self.rows.keys())
            if before.get((name, version)) != self.rows.get((name, version))
        )
        return Revision(self.base.fingerprint, self.preview().fingerprint, changes)


def reverse_index(repository: Repository) -> dict[str, tuple[tuple[str, str], ...]]:
    result = {name: set() for name in repository.names()}
    for release in repository.all():
        for dependency in release.dependencies:
            result.setdefault(dependency.name, set()).add(release.identity)
    return {name: tuple(sorted(parents)) for name, parents in sorted(result.items())}


def affected(repository: Repository, names: tuple[str, ...]) -> tuple[str, ...]:
    reverse = reverse_index(repository)
    pending = [normalize(name) for name in names]
    visited = set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        pending.extend(parent for parent, version in reverse.get(name, ()) if parent not in visited)
    return tuple(sorted(visited))
