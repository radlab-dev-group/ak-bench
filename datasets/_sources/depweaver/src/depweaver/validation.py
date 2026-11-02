"""Validate a proposed resolution independently of the search implementation."""

from dataclasses import dataclass

from .model import Request, Resolution
from .repository import Repository
from .versions import Version


@dataclass(frozen=True)
class Violation:
    code: str
    package: str
    message: str


def validate(
    repository: Repository, request: Request, resolution: Resolution
) -> tuple[Violation, ...]:
    violations = []

    def report(code, package, message):
        violations.append(Violation(code, package, message))

    if resolution.target != request.target:
        report("target", "", "resolution target differs from request")
    if resolution.request_fingerprint != request.fingerprint:
        report("request", "", "resolution fingerprint differs from request")
    if resolution.repository_fingerprint != repository.fingerprint:
        report("repository", "", "repository fingerprint mismatch")
    selected = {release.name: release for release in resolution.selected}
    if len(selected) != len(resolution.selected):
        report("duplicate", "", "package selected more than once")
    constraints, features = {}, {}
    for root in request.roots:
        if root.marker.matches(request.target):
            constraints.setdefault(root.name, []).append(root)
            features[root.name] = features.get(root.name, frozenset()) | root.extras
    processed = set()
    while True:
        ready = [
            (name, tuple(sorted(features.get(name, ()))))
            for name in constraints
            if name in selected
        ]
        ready = [key for key in ready if key not in processed]
        if not ready:
            break
        for name, extras in ready:
            processed.add((name, extras))
            release = selected[name]
            for dependency in release.dependencies:
                if dependency.marker.matches(request.target, frozenset(extras)):
                    rows = constraints.setdefault(dependency.name, [])
                    if dependency not in rows:
                        rows.append(dependency)
                    features[dependency.name] = (
                        features.get(dependency.name, frozenset()) | dependency.extras
                    )
    for name, rows in sorted(constraints.items()):
        if name not in selected:
            report("missing", name, "active dependency is not selected")
            continue
        release = selected[name]
        try:
            original = repository.get(name, release.version)
            if original != release:
                report("metadata", name, "selected release differs from repository")
        except KeyError:
            report("unknown", name, "selected release does not exist")
        if not all(dependency.spec.matches(release.version) for dependency in rows):
            report("version", name, "selected version violates a requirement")
        if not features.get(name, frozenset()) <= release.extras:
            report("extras", name, "selected release lacks requested extras")
        if not release.requires_python.matches(Version.coerce(request.target.python_version)):
            report("python", name, "selected release cannot run on target Python")
        locked = dict(request.locked).get(name)
        same_lock = locked is not None and release.version == Version.parse(locked)
        if locked and name not in request.update and not same_lock:
            report("lock", name, "unchanged package moved away from its pin")
        if release.yanked and not request.policy.allow_yanked and not same_lock:
            report("yanked", name, "selected release is yanked")
        if (
            release.version.prerelease
            and not request.policy.allow_prerelease
            and not same_lock
            and not any(dependency.spec.allows_prerelease for dependency in rows)
        ):
            report("prerelease", name, "unrequested prerelease selected")
    for name in sorted(selected.keys() - constraints.keys()):
        report("orphan", name, "selected package is unreachable")
    expected = tuple((name, tuple(sorted(features.get(name, ())))) for name in sorted(selected))
    if resolution.extras != expected:
        report("feature-closure", "", "reported extras differ from active requirement closure")
    return tuple(violations)


def require_valid(repository: Repository, request: Request, resolution: Resolution) -> None:
    violations = validate(repository, request, resolution)
    if violations:
        raise ValueError(
            "; ".join(f"{item.code}:{item.package}: {item.message}" for item in violations)
        )
