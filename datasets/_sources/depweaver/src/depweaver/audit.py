"""Offline advisory matching with dependency paths and upgrade candidates."""

from dataclasses import dataclass, field

from .graph import Graph
from .markers import Marker
from .model import Resolution, normalize
from .repository import Repository
from .versions import Spec, Version

SEVERITIES = {"low": 1, "moderate": 2, "high": 3, "critical": 4}


@dataclass(frozen=True)
class Advisory:
    identity: str
    package: str
    affected: Spec
    severity: str
    summary: str
    marker: Marker = field(default_factory=Marker)

    def __post_init__(self) -> None:
        if not self.identity or self.severity not in SEVERITIES:
            raise ValueError("invalid advisory identity or severity")
        object.__setattr__(self, "package", normalize(self.package))
        if isinstance(self.affected, str):
            object.__setattr__(self, "affected", Spec.parse(self.affected))
        if isinstance(self.marker, str):
            object.__setattr__(self, "marker", Marker(self.marker))

    def document(self) -> dict:
        return {
            "identity": self.identity,
            "package": self.package,
            "affected": str(self.affected),
            "severity": self.severity,
            "summary": self.summary,
            "marker": self.marker.text,
        }


class Database:
    def __init__(self, advisories: tuple[Advisory, ...] = ()) -> None:
        if len({item.identity for item in advisories}) != len(advisories):
            raise ValueError("duplicate advisory identity")
        self.advisories = tuple(sorted(advisories, key=lambda item: item.identity))

    def document(self) -> dict:
        return {"version": 1, "advisories": [item.document() for item in self.advisories]}

    @classmethod
    def load(cls, document: dict) -> "Database":
        if document.get("version") != 1 or not isinstance(document.get("advisories"), list):
            raise ValueError("invalid advisory database")
        return cls(tuple(Advisory(**row) for row in document["advisories"]))


@dataclass(frozen=True)
class Finding:
    advisory: Advisory
    version: Version
    paths: tuple[tuple[str, ...], ...]
    safe_versions: tuple[str, ...]

    def document(self) -> dict:
        return {
            "advisory": self.advisory.document(),
            "version": str(self.version),
            "paths": [list(path) for path in self.paths],
            "safe_versions": list(self.safe_versions),
        }


def audit(
    repository: Repository,
    resolution: Resolution,
    database: Database,
    *,
    roots: tuple[str, ...] = (),
    minimum: str = "low",
    ignored: frozenset[str] = frozenset(),
) -> tuple[Finding, ...]:
    if minimum not in SEVERITIES:
        raise ValueError("unknown minimum severity")
    graph = Graph.from_resolution(resolution)
    selected = {release.name: release for release in resolution.selected}
    roots = tuple(normalize(root) for root in roots) or tuple(
        name for name in graph.names if not graph.reverse[name]
    )
    findings = []
    for advisory in database.advisories:
        if advisory.identity in ignored or SEVERITIES[advisory.severity] < SEVERITIES[minimum]:
            continue
        release = selected.get(advisory.package)
        if (
            release is None
            or not advisory.affected.matches(release.version)
            or not advisory.marker.matches(resolution.target)
        ):
            continue
        paths = tuple(
            path for root in roots if (path := graph.shortest_path(root, release.name)) is not None
        )
        relevant = [
            item
            for item in database.advisories
            if item.package == release.name and item.marker.matches(resolution.target)
        ]
        safe = tuple(
            str(candidate.version)
            for candidate in repository.versions(release.name)
            if candidate.version >= release.version
            and not candidate.yanked
            and candidate.requires_python.matches(Version.coerce(resolution.target.python_version))
            and all(not item.affected.matches(candidate.version) for item in relevant)
        )
        findings.append(Finding(advisory, release.version, paths, safe))
    return tuple(
        sorted(
            findings, key=lambda item: (-SEVERITIES[item.advisory.severity], item.advisory.identity)
        )
    )


def summarize(findings: tuple[Finding, ...]) -> dict:
    counts = dict.fromkeys(SEVERITIES, 0)
    for finding in findings:
        counts[finding.advisory.severity] += 1
    return {
        "count": len(findings),
        "by_severity": counts,
        "packages": sorted({finding.advisory.package for finding in findings}),
        "unpatched": sorted(
            {finding.advisory.package for finding in findings if not finding.safe_versions}
        ),
    }
