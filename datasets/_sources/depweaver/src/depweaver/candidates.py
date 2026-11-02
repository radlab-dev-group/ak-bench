"""Repository domains: metadata eligibility, pins, prereleases and stable ordering."""

from .model import Release, Request
from .propagation import State
from .repository import Repository
from .versions import Version


def pinned_version(name: str, request: Request) -> str | None:
    locks = dict(request.locked)
    if name in locks and name not in request.update:
        return locks[name]
    return None


def eligible(release: Release, name: str, state: State, request: Request) -> bool:
    constraints = state.constraints[name]
    if not all(row.dependency.spec.matches(release.version) for row in constraints):
        return False
    if not state.extras.get(name, frozenset()) <= release.extras:
        return False
    if not release.requires_python.matches(Version.coerce(request.target.python_version)):
        return False
    locked = dict(request.locked).get(name)
    same_lock = locked is not None and release.version == Version.parse(locked)
    if release.yanked and not request.policy.allow_yanked and not same_lock:
        return False
    if (
        release.version.prerelease
        and not request.policy.allow_prerelease
        and not same_lock
        and not any(row.dependency.spec.allows_prerelease for row in constraints)
    ):
        return False
    pin = pinned_version(name, request)
    return pin is None or release.version == Version.parse(pin)


class CandidateCache:
    def __init__(self) -> None:
        self.values: dict[tuple, tuple[Release, ...]] = {}
        self.hits = 0
        self.misses = 0

    def key(self, repository: Repository, name: str, state: State, request: Request) -> tuple:
        return (
            repository.fingerprint,
            name,
            tuple(sorted(str(row.dependency.spec) for row in state.constraints[name])),
            tuple(sorted(state.extras.get(name, frozenset()))),
            request.target.fingerprint,
            tuple(sorted(request.policy.document().items())),
            request.locked,
            tuple(sorted(request.update)),
        )

    def candidates(
        self, repository: Repository, name: str, state: State, request: Request
    ) -> tuple[Release, ...]:
        key = self.key(repository, name, state, request)
        if key in self.values:
            self.hits += 1
            return self.values[key]
        self.misses += 1
        releases = [
            release
            for release in repository.versions(name)
            if eligible(release, name, state, request)
        ]
        releases.sort(key=lambda release: release.version, reverse=not request.policy.prefer_lowest)
        result = tuple(releases)
        self.values[key] = result
        return result

    def clear(self) -> None:
        self.values.clear()
        self.hits = self.misses = 0
