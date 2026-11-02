"""Stable human-facing reports over metadata, locks and graph structure."""

from collections import deque
from dataclasses import asdict, dataclass

from .graph import Graph
from .lockfile import Lockfile, diff
from .model import Request, Resolution, normalize
from .repository import Repository
from .versions import Spec, Version


@dataclass(frozen=True)
class Row:
    name: str
    version: str
    extras: tuple[str, ...]
    direct: bool
    required_by: tuple[str, ...]
    dependencies: tuple[str, ...]

    def document(self) -> dict:
        return asdict(self)


def rows(resolution: Resolution, request: Request | None = None) -> tuple[Row, ...]:
    graph = Graph.from_resolution(resolution)
    direct = (
        {root.name for root in request.roots if root.marker.matches(request.target)}
        if request
        else set()
    )
    extras = dict(resolution.extras)
    return tuple(
        Row(
            release.name,
            str(release.version),
            extras[release.name],
            release.name in direct,
            tuple(sorted(graph.reverse[release.name])),
            tuple(sorted(graph.forward[release.name])),
        )
        for release in resolution.selected
    )


def table(resolution: Resolution, request: Request | None = None) -> str:
    records = rows(resolution, request)
    headings = ("Package", "Version", "Extras", "Required by")
    values = [headings]
    for row in records:
        values.append(
            (
                row.name,
                row.version,
                ",".join(row.extras),
                "<root>" if row.direct else ",".join(row.required_by),
            )
        )
    widths = tuple(max(len(row[index]) for row in values) for index in range(4))
    return (
        "\n".join(
            "  ".join(value.ljust(width) for value, width in zip(row, widths, strict=True)).rstrip()
            for row in values
        )
        + "\n"
    )


def tree(resolution: Resolution, *, roots: tuple[str, ...] = (), max_depth: int = 50) -> str:
    if type(max_depth) is not int or max_depth < 0:
        raise ValueError("invalid tree depth limit")
    graph = Graph.from_resolution(resolution)
    versions = resolution.versions()
    roots = tuple(normalize(name) for name in roots)
    if set(roots) - set(graph.names):
        raise KeyError("unknown tree root")
    if not roots:
        roots = tuple(name for name in graph.names if not graph.reverse[name])
        covered = set(graph.reachable(roots))
        # Cyclic components may have no node without an incoming edge.
        for group in graph.components():
            if not set(group) <= covered:
                roots += (group[0],)
                covered.update(graph.reachable((group[0],)))
    lines = []

    def visit(name, path, prefix):
        cycle = name in path
        lines.append(prefix + name + " " + versions[name] + (" (cycle)" if cycle else ""))
        if cycle:
            return
        children = sorted(graph.forward[name])
        if len(path) >= max_depth:
            if children:
                lines.append(prefix + "  ...")
            return
        for child in children:
            visit(child, (*path, name), prefix + "  ")

    for root in roots:
        visit(root, (), "")
    return "\n".join(lines) + ("\n" if lines else "")


def statistics(resolution: Resolution) -> dict:
    graph = Graph.from_resolution(resolution)
    components = graph.components()
    cycles = [
        group for group in components if len(group) > 1 or group[0] in graph.forward[group[0]]
    ]
    return {
        "packages": len(graph.names),
        "edges": len(graph.edges),
        "components": len(components),
        "cycles": [list(group) for group in cycles],
        "install_layers": len(graph.layers()),
        "features": sum(len(extras) for name, extras in resolution.extras),
        "yanked": sorted(release.name for release in resolution.selected if release.yanked),
        "prerelease": sorted(
            release.name for release in resolution.selected if release.version.prerelease
        ),
        "without_digests": sorted(
            release.name for release in resolution.selected if not release.digest
        ),
    }


def outdated(
    repository: Repository, resolution: Resolution, *, allow_prerelease: bool = False
) -> tuple[dict, ...]:
    result = []
    extras = dict(resolution.extras)
    for release in resolution.selected:
        candidates = [
            candidate
            for candidate in repository.versions(release.name)
            if not candidate.yanked
            and (allow_prerelease or not candidate.version.prerelease)
            and candidate.requires_python.matches(Version.coerce(resolution.target.python_version))
            and set(extras[release.name]) <= candidate.extras
        ]
        if candidates and candidates[0].version > release.version:
            result.append(
                {
                    "name": release.name,
                    "current": str(release.version),
                    "latest": str(candidates[0].version),
                    "breaking": candidates[0].version.major != release.version.major,
                }
            )
    return tuple(result)


def changes(before: Resolution, after: Resolution) -> dict:
    difference = diff(Lockfile(before), Lockfile(after))
    first_graph, second_graph = Graph.from_resolution(before), Graph.from_resolution(after)
    impacted = set()
    changed = set(difference.added) | set(difference.removed) | set(difference.features)
    changed.update(name for name, old, new in (*difference.upgraded, *difference.downgraded))
    for graph in (first_graph, second_graph):
        roots = tuple(sorted(changed & set(graph.names)))
        impacted.update(graph.reachable(roots, reverse=True))
    return {
        **asdict(difference),
        "impacted": sorted(impacted),
        "target_changed": before.target != after.target,
    }


def search(
    repository: Repository,
    name: str = "",
    spec: str = "*",
    *,
    extras: frozenset[str] = frozenset(),
    include_yanked: bool = False,
) -> tuple[dict, ...]:
    constraint = Spec.parse(spec)
    query = name.lower().replace("_", "-")
    return tuple(
        release.document()
        for release in repository.all()
        if query in release.name
        and constraint.matches(release.version)
        and extras <= release.extras
        and (include_yanked or not release.yanked)
    )


def root_distances(resolution: Resolution, roots: tuple[str, ...]) -> dict[str, int | None]:
    graph = Graph.from_resolution(resolution)
    if set(roots) - set(graph.names):
        raise KeyError("unknown distance root")
    distances = dict.fromkeys(graph.names)
    pending = deque((root, 0) for root in sorted(set(roots)))
    while pending:
        name, distance = pending.popleft()
        if distances[name] is not None:
            continue
        distances[name] = distance
        pending.extend((child, distance + 1) for child in sorted(graph.forward[name]))
    return distances
