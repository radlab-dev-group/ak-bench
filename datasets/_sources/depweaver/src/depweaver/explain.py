"""Resolution explanations derived from immutable results rather than solver state."""

from collections import deque
from dataclasses import dataclass

from .errors import Conflict
from .graph import Graph
from .model import Dependency, Request, Resolution, normalize
from .repository import Repository
from .validation import require_valid
from .versions import Version


@dataclass(frozen=True)
class Reason:
    parent: str | None
    dependency: Dependency
    path: tuple[str, ...]

    def document(self) -> dict:
        return {
            "parent": self.parent,
            "dependency": self.dependency.document(),
            "path": list(self.path),
        }


@dataclass(frozen=True)
class Rejected:
    version: str
    reasons: tuple[str, ...]

    def document(self) -> dict:
        return {"version": self.version, "reasons": list(self.reasons)}


class Explanation:
    def __init__(self, repository: Repository, request: Request, resolution: Resolution) -> None:
        require_valid(repository, request, resolution)
        self.repository, self.request, self.resolution = repository, request, resolution
        self.graph = Graph.from_resolution(resolution)
        self.selected = {release.name: release for release in resolution.selected}
        self.features = {name: frozenset(values) for name, values in resolution.extras}
        self.roots = tuple(
            sorted({root.name for root in request.roots if root.marker.matches(request.target)})
        )

    def path(self, name: str) -> tuple[str, ...] | None:
        name = normalize(name)
        if name not in self.selected:
            raise KeyError(name)
        candidates = [
            path
            for root in self.roots
            if (path := self.graph.shortest_path(root, name)) is not None
        ]
        return min(candidates, key=lambda path: (len(path), path)) if candidates else None

    def reasons(self, name: str) -> tuple[Reason, ...]:
        name = normalize(name)
        if name not in self.selected:
            raise KeyError(name)
        result = []
        for root in self.request.roots:
            if root.name == name and root.marker.matches(self.request.target):
                result.append(Reason(None, root, (name,)))
        for release in self.resolution.selected:
            for dependency in release.dependencies:
                if dependency.name == name and dependency.marker.matches(
                    self.request.target, self.features[release.name]
                ):
                    path = self.path(release.name)
                    result.append(
                        Reason(
                            release.name,
                            dependency,
                            (*path, name) if path else (release.name, name),
                        )
                    )
        return tuple(
            sorted(
                result,
                key=lambda item: (
                    item.parent or "",
                    str(item.dependency.spec),
                    item.dependency.marker.text,
                    tuple(sorted(item.dependency.extras)),
                ),
            )
        )

    def alternatives(self, name: str) -> tuple[Rejected, ...]:
        name = normalize(name)
        selected = self.selected[name]
        constraints = self.reasons(name)
        locked = dict(self.request.locked).get(name)
        result = []
        for release in self.repository.versions(name):
            if release.version == selected.version:
                continue
            reasons = []
            if any(not item.dependency.spec.matches(release.version) for item in constraints):
                reasons.append("requirement")
            if not self.features[name] <= release.extras:
                reasons.append("extras")
            if not release.requires_python.matches(
                Version.coerce(self.request.target.python_version)
            ):
                reasons.append("python")
            same_lock = locked is not None and Version.parse(locked) == release.version
            if locked and name not in self.request.update and not same_lock:
                reasons.append("locked")
            if release.yanked and not self.request.policy.allow_yanked and not same_lock:
                reasons.append("yanked")
            if (
                release.version.prerelease
                and not self.request.policy.allow_prerelease
                and not same_lock
            ) and not any(item.dependency.spec.allows_prerelease for item in constraints):
                reasons.append("prerelease")
            result.append(
                Rejected(
                    str(release.version),
                    tuple(reasons) or ("search-preference-or-transitive-conflict",),
                )
            )
        return tuple(result)

    def package(self, name: str) -> dict:
        name = normalize(name)
        return {
            "name": name,
            "version": str(self.selected[name].version),
            "extras": sorted(self.features[name]),
            "path": list(self.path(name) or ()),
            "reasons": [reason.document() for reason in self.reasons(name)],
            "alternatives": [item.document() for item in self.alternatives(name)],
        }

    def document(self) -> dict:
        return {
            "version": 1,
            "request": self.request.fingerprint,
            "repository": self.repository.fingerprint,
            "packages": [self.package(name) for name in sorted(self.selected)],
        }


def render_conflict(conflict: Conflict) -> str:
    lines = [f"Cannot resolve {conflict.package}: {conflict.reason}."]
    for constraint in sorted(conflict.constraints, key=lambda item: item.fingerprint):
        parent = "root request" if constraint.parent is None else " ".join(constraint.parent)
        dependency = constraint.dependency
        extras = "[" + ",".join(sorted(dependency.extras)) + "]" if dependency.extras else ""
        lines.append(f"  {parent} requires {dependency.name}{extras} {dependency.spec}.")
    if conflict.culprits:
        lines.append(
            "  Conflicting selections: "
            + ", ".join(" ".join(pair) for pair in sorted(conflict.culprits))
            + "."
        )
    return "\n".join(lines)


def feature_sources(
    request: Request, resolution: Resolution
) -> dict[str, dict[str, tuple[str, ...]]]:
    """Trace feature activation to roots without relying on branch caches."""
    selected = {release.name: release for release in resolution.selected}
    features: dict[str, set[str]] = {}
    sources: dict[str, dict[str, set[str]]] = {}
    queue = deque(("<root>", root) for root in request.roots if root.marker.matches(request.target))
    expanded = set()
    while queue:
        parent, dependency = queue.popleft()
        if dependency.name not in selected:
            raise ValueError("feature graph references an unselected package")
        active = features.setdefault(dependency.name, set())
        active.update(dependency.extras)
        for extra in dependency.extras:
            sources.setdefault(dependency.name, {}).setdefault(extra, set()).add(parent)
        release = selected[dependency.name]
        key = release.name, tuple(sorted(active))
        if key in expanded:
            continue
        expanded.add(key)
        queue.extend(
            (release.name, child)
            for child in release.dependencies
            if child.marker.matches(request.target, frozenset(active))
        )
    return {
        name: {extra: tuple(sorted(parents)) for extra, parents in sorted(extras.items())}
        for name, extras in sorted(sources.items())
    }
