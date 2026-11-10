"""Canonical lockfile form: layered install order, normalised markers, one digest.

The canonical form of a resolution is a JSON document whose package rows are
ordered by the key ``(layer, name, version, extras)`` described in
``docs/lockfile-canonical-form.md`` and SPEC.md ("Lockfile canonical form and
proofs"). The layer of a package is its height in the condensation of the
active dependency graph: packages that depend on nothing selected sit in layer
0, and a package sits one layer above the highest package it actively depends
on. Members of one dependency cycle share a layer. The order is therefore the
install order, not the alphabetical order.
"""

import hashlib
from dataclasses import dataclass

from .markers import Expression, Marker
from .model import Dependency, Release, Resolution, canonical, normalize
from .versions import Version

CANONICAL_VERSION = 1


def _resolution(value: object) -> Resolution:
    if isinstance(value, Resolution):
        return value
    resolution = getattr(value, "resolution", None)
    if isinstance(resolution, Resolution):
        return resolution
    raise ValueError("expected a Resolution or a Lockfile")


def canonical_version(version: Version | str) -> str:
    version = Version.parse(version) if isinstance(version, str) else version
    return str(version.without_build())


def canonical_extras(extras) -> tuple[str, ...]:
    return tuple(sorted({normalize(extra) for extra in extras}))


def _render(expression: Expression, *, parent: str | None = None) -> str:
    if expression.operation == "true":
        return ""
    if expression.operation == "compare":
        field, operation, literal = expression.arguments
        if operation in {"in", "not in"}:
            literal = ",".join(sorted(set(literal.split(","))))
        elif field == "python_version":
            literal = canonical_version(Version.coerce(literal))
        return f"{field} {operation} " + canonical(literal)
    rendered = sorted(
        {_render(operand, parent=expression.operation) for operand in _flatten(expression)}
    )
    text = f" {expression.operation} ".join(rendered)
    if expression.operation == "or" and parent == "and":
        return "(" + text + ")"
    return text


def _flatten(expression: Expression) -> list[Expression]:
    result = []
    for argument in expression.arguments:
        if argument.operation == expression.operation:
            result.extend(_flatten(argument))
        else:
            result.append(argument)
    return result


def canonical_marker(marker: Marker | str) -> str:
    marker = Marker(marker) if isinstance(marker, str) else marker
    return _render(marker.expression())


def canonical_dependency(dependency: Dependency) -> dict:
    return {
        "name": normalize(dependency.name),
        "spec": str(dependency.spec),
        "extras": list(canonical_extras(dependency.extras)),
        "marker": canonical_marker(dependency.marker),
    }


def _dependency_key(row: dict) -> tuple:
    return row["name"], row["marker"], row["spec"], tuple(row["extras"])


def active_edges(resolution: Resolution) -> dict[str, tuple[str, ...]]:
    """Map each selected package to the selected packages it actively depends on."""

    selected = {release.name: release for release in resolution.selected}
    features = {name: frozenset(extras) for name, extras in resolution.extras}
    edges = {}
    for name, release in selected.items():
        targets = set()
        for dependency in release.dependencies:
            if dependency.name in selected and dependency.marker.matches(
                resolution.target, features.get(name, frozenset())
            ):
                targets.add(dependency.name)
        targets.discard(name)
        edges[name] = tuple(sorted(targets))
    return edges


def _components(edges: dict[str, tuple[str, ...]]) -> dict[str, int]:
    """Tarjan's strongly connected components, iterative, keyed by package name."""

    index = {}
    lowlink = {}
    component = {}
    stack = []
    on_stack = set()
    counter = 0
    components = 0
    for root in sorted(edges):
        if root in index:
            continue
        work = [(root, iter(edges[root]))]
        index[root] = lowlink[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, successors = work[-1]
            advanced = False
            for successor in successors:
                if successor not in index:
                    index[successor] = lowlink[successor] = counter
                    counter += 1
                    stack.append(successor)
                    on_stack.add(successor)
                    work.append((successor, iter(edges[successor])))
                    advanced = True
                    break
                if successor in on_stack:
                    lowlink[node] = min(lowlink[node], index[successor])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[node])
            if lowlink[node] == index[node]:
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component[member] = components
                    if member == node:
                        break
                components += 1
    return component


def layers(resolution: Resolution) -> dict[str, int]:
    """Height of every selected package in the condensed active dependency graph."""

    edges = active_edges(resolution)
    component = _components(edges)
    successors: dict[int, set[int]] = {}
    for name, targets in edges.items():
        own = component[name]
        successors.setdefault(own, set())
        for target in targets:
            other = component[target]
            if other != own:
                successors[own].add(other)
    height: dict[int, int] = {}

    def resolve(node: int) -> int:
        pending = [node]
        while pending:
            current = pending[-1]
            if current in height:
                pending.pop()
                continue
            unresolved = [child for child in successors[current] if child not in height]
            if unresolved:
                pending.extend(unresolved)
                continue
            height[current] = (
                1 + max(height[child] for child in successors[current])
                if successors[current]
                else 0
            )
            pending.pop()
        return height[node]

    return {name: resolve(component[name]) for name in sorted(edges)}


@dataclass(frozen=True)
class Row:
    layer: int
    name: str
    version: str
    extras: tuple[str, ...]
    release: Release

    @property
    def key(self) -> tuple:
        return self.layer, self.name, Version.parse(self.version), self.extras

    def document(self) -> dict:
        requires = sorted(
            (canonical_dependency(dependency) for dependency in self.release.dependencies),
            key=_dependency_key,
        )
        return {
            "layer": self.layer,
            "name": self.name,
            "version": self.version,
            "extras": list(self.extras),
            "provides": list(canonical_extras(self.release.extras)),
            "requires": requires,
            "requires_python": str(self.release.requires_python),
            "yanked": self.release.yanked,
            "artifact": self.release.digest,
        }


def _canonical_rows(value: object) -> tuple[Row, ...]:
    resolution = _resolution(value)
    features = dict(resolution.extras)
    heights = layers(resolution)
    rows = [
        Row(
            heights[release.name],
            normalize(release.name),
            canonical_version(release.version),
            canonical_extras(features.get(release.name, ())),
            release,
        )
        for release in resolution.selected
    ]
    return tuple(sorted(rows, key=lambda row: row.key))


def canonical_order(value: object) -> tuple[tuple[str, str], ...]:
    return tuple((row.name, row.version) for row in _canonical_rows(value))


def canonical_document(value: object) -> dict:
    resolution = _resolution(value)
    return {
        "version": CANONICAL_VERSION,
        "target": resolution.target.document(),
        "packages": [row.document() for row in _canonical_rows(resolution)],
    }


def lock_digest(value: object) -> str:
    return hashlib.sha256(canonical(canonical_document(value)).encode()).hexdigest()
