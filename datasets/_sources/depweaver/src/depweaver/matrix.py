"""Multi-target resolution with per-target isolation and portable bundle validation."""

import hashlib
from dataclasses import dataclass

from .errors import Unsatisfiable
from .lockfile import Lockfile
from .manifest import Manifest
from .model import Request, Resolution, canonical
from .repository import Repository
from .resolver import Resolver
from .validation import require_valid


@dataclass(frozen=True)
class TargetFailure:
    name: str
    explanation: dict


@dataclass(frozen=True)
class Bundle:
    results: tuple[tuple[str, Resolution], ...]

    def document(self) -> dict:
        body = {
            "version": 1,
            "targets": {name: Lockfile(result).document() for name, result in self.results},
        }
        return {"body": body, "sha256": hashlib.sha256(canonical(body).encode()).hexdigest()}

    @classmethod
    def load(cls, document: dict) -> "Bundle":
        body = document["body"]
        if (
            body.get("version") != 1
            or hashlib.sha256(canonical(body).encode()).hexdigest() != document["sha256"]
        ):
            raise ValueError("invalid resolution bundle")
        if not isinstance(body.get("targets"), dict):
            raise ValueError("bundle targets must be an object")
        results = tuple(
            (name, Lockfile.load(row).resolution) for name, row in sorted(body["targets"].items())
        )
        repositories = {result.repository_fingerprint for name, result in results}
        if len(repositories) > 1:
            raise ValueError("bundle targets came from different repository snapshots")
        return cls(results)

    def variants(self) -> dict[str, dict[str, tuple[str, ...]]]:
        packages = {}
        for name, resolution in self.results:
            for release in resolution.selected:
                packages.setdefault(release.name, {}).setdefault(str(release.version), []).append(
                    name
                )
        return {
            package: {
                version: tuple(sorted(targets)) for version, targets in sorted(versions.items())
            }
            for package, versions in sorted(packages.items())
        }

    def common(self) -> dict[str, str]:
        if not self.results:
            return {}
        common = self.results[0][1].versions()
        for _name, resolution in self.results[1:]:
            versions = resolution.versions()
            common = {
                package: version
                for package, version in common.items()
                if versions.get(package) == version
            }
        return common

    def conflicts(self) -> dict[str, tuple[str, ...]]:
        return {
            package: tuple(versions)
            for package, versions in self.variants().items()
            if len(versions) > 1
        }


@dataclass(frozen=True)
class MatrixResult:
    bundle: Bundle
    failures: tuple[TargetFailure, ...]

    @property
    def ok(self) -> bool:
        return not self.failures


def solve(
    repository: Repository, requests: dict[str, Request], *, keep_going: bool = True
) -> MatrixResult:
    solver = Resolver(repository)
    results, failures = [], []
    for name, request in sorted(requests.items()):
        try:
            resolution = solver.solve(request)
            require_valid(repository, request, resolution)
        except Unsatisfiable as error:
            failures.append(TargetFailure(name, error.conflict.document()))
            if not keep_going:
                break
        else:
            results.append((name, resolution))
    return MatrixResult(Bundle(tuple(results)), tuple(failures))


def profiles(
    repository: Repository, manifest: Manifest, *, names: tuple[str, ...] = ()
) -> MatrixResult:
    wanted = set(names) or {profile.name for profile in manifest.profiles}
    available = {profile.name for profile in manifest.profiles}
    if wanted - available:
        raise ValueError("unknown matrix profile")
    return solve(repository, {name: manifest.request(name) for name in sorted(wanted)})
