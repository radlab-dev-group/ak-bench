"""Constraint diagnostics, root conflict minimization and lock update impact."""

from dataclasses import dataclass, replace

from .errors import SearchLimit, Unsatisfiable
from .graph import Graph
from .model import Dependency, Request, Resolution, normalize
from .repository import Repository
from .resolver import Resolver
from .versions import Version


@dataclass(frozen=True)
class Trial:
    roots: tuple[Dependency, ...]
    satisfiable: bool | None
    decisions: int
    explanation: dict | None

    def document(self) -> dict:
        return {
            "roots": [root.document() for root in self.roots],
            "satisfiable": self.satisfiable,
            "decisions": self.decisions,
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class Core:
    roots: tuple[Dependency, ...]
    minimal: bool
    trials: tuple[Trial, ...]

    def document(self) -> dict:
        return {
            "roots": [root.document() for root in self.roots],
            "minimal": self.minimal,
            "trials": [trial.document() for trial in self.trials],
        }


class Analyzer:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def trial(self, request: Request) -> Trial:
        solver = Resolver(self.repository)
        try:
            solver.solve(request)
        except Unsatisfiable as error:
            return Trial(
                request.roots, False, solver.statistics.decisions, error.conflict.document()
            )
        except SearchLimit:
            return Trial(
                request.roots, None, solver.statistics.decisions, {"reason": "search-limit"}
            )
        return Trial(request.roots, True, solver.statistics.decisions, None)

    def core(self, request: Request, *, max_trials: int = 1000) -> Core:
        """Find a deletion-minimal root core; never claim minimum cardinality."""
        if type(max_trials) is not int or max_trials < 1:
            raise ValueError("invalid conflict analysis trial limit")
        trials = [self.trial(request)]
        if trials[0].satisfiable is True:
            raise ValueError("cannot minimize a satisfiable request")
        if trials[0].satisfiable is None:
            return Core(request.roots, False, tuple(trials))
        roots = list(request.roots)
        index = 0
        complete = True
        while index < len(roots):
            if len(trials) >= max_trials:
                complete = False
                break
            candidate = tuple(roots[:index] + roots[index + 1 :])
            trial = self.trial(replace(request, roots=candidate))
            trials.append(trial)
            if trial.satisfiable is False:
                roots.pop(index)
            else:
                if trial.satisfiable is None:
                    complete = False
                index += 1
        return Core(tuple(roots), complete, tuple(trials))

    def direct_domains(self, request: Request) -> dict[str, dict]:
        active = {}
        for dependency in request.roots:
            if dependency.marker.matches(request.target):
                active.setdefault(dependency.name, []).append(dependency)
        domains = {}
        pins = dict(request.locked)
        for name, requirements in sorted(active.items()):
            features = frozenset().union(*(dependency.extras for dependency in requirements))
            accepted, rejected = [], {}
            for release in self.repository.versions(name):
                reasons = []
                if any(not dependency.spec.matches(release.version) for dependency in requirements):
                    reasons.append("range")
                if not features <= release.extras:
                    reasons.append("extras")
                if not release.requires_python.matches(
                    Version.coerce(request.target.python_version)
                ):
                    reasons.append("python")
                locked = name in pins and release.version == Version.parse(pins[name])
                if name in pins and name not in request.update and not locked:
                    reasons.append("pin")
                if release.yanked and not request.policy.allow_yanked and not locked:
                    reasons.append("yanked")
                if (
                    release.version.prerelease
                    and not request.policy.allow_prerelease
                    and not locked
                    and not any(dependency.spec.allows_prerelease for dependency in requirements)
                ):
                    reasons.append("prerelease")
                if reasons:
                    rejected[str(release.version)] = reasons
                else:
                    accepted.append(str(release.version))
            domains[name] = {"accepted": accepted, "rejected": rejected, "extras": sorted(features)}
        return domains


@dataclass(frozen=True)
class Impact:
    requested: tuple[str, ...]
    dependencies: tuple[str, ...]
    dependents: tuple[str, ...]
    retained_pins: tuple[tuple[str, str], ...]

    def document(self) -> dict:
        return {
            "requested": list(self.requested),
            "dependencies": list(self.dependencies),
            "dependents": list(self.dependents),
            "retained_pins": dict(self.retained_pins),
        }


def update_impact(resolution: Resolution, names: frozenset[str]) -> Impact:
    graph = Graph.from_resolution(resolution)
    requested = tuple(sorted({normalize(name) for name in names}))
    if set(requested) - set(graph.names):
        raise ValueError("update impact requested for an unlocked package")
    dependencies = graph.reachable(requested)
    dependents = graph.reachable(requested, reverse=True)
    retained = tuple(
        (name, version)
        for name, version in sorted(resolution.versions().items())
        if name not in requested
    )
    return Impact(requested, dependencies, dependents, retained)


def intersect_roots(request: Request) -> tuple[Dependency, ...]:
    """Consolidate only active root requirements; preserve owner marker semantics."""
    active = {}
    for dependency in request.roots:
        if not dependency.marker.matches(request.target):
            continue
        previous = active.get(dependency.name)
        active[dependency.name] = (
            Dependency(
                dependency.name,
                previous.spec & dependency.spec,
                previous.extras | dependency.extras,
            )
            if previous
            else Dependency(dependency.name, dependency.spec, dependency.extras)
        )
    return tuple(active[name] for name in sorted(active))
