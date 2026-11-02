"""Recompute reachable constraints and monotone feature activation to a fixed point."""

from dataclasses import dataclass, field

from .errors import Conflict
from .model import Constraint, Dependency, Release, Request


@dataclass
class State:
    constraints: dict[str, list[Constraint]] = field(default_factory=dict)
    extras: dict[str, frozenset[str]] = field(default_factory=dict)
    selected: dict[str, Release] = field(default_factory=dict)
    expansion_keys: set[tuple] = field(default_factory=set)

    def add(self, dependency: Dependency, parent: tuple[str, str] | None) -> bool:
        name = dependency.name
        constraint = Constraint(dependency, parent)
        rows = self.constraints.setdefault(name, [])
        changed = False
        if constraint not in rows:
            rows.append(constraint)
            changed = True
        previous = self.extras.get(name, frozenset())
        combined = previous | dependency.extras
        self.extras[name] = combined
        return changed or combined != previous

    def explanation(self, package: str) -> frozenset[tuple[str, str]]:
        result, seen = set(), set()

        def visit(name):
            if name in seen:
                return
            seen.add(name)
            if name in self.selected:
                result.add(self.selected[name].identity)
            for constraint in self.constraints.get(name, ()):
                if constraint.parent is not None:
                    result.add(constraint.parent)
                    visit(constraint.parent[0])

        visit(package)
        return frozenset(result)

    def conflict(self) -> Conflict | None:
        for name, release in sorted(self.selected.items()):
            if not all(
                row.dependency.spec.matches(release.version) for row in self.constraints[name]
            ):
                return Conflict(
                    name,
                    "selected version violates an active requirement",
                    self.explanation(name),
                    tuple(self.constraints[name]),
                )
            if not self.extras[name] <= release.extras:
                return Conflict(
                    name,
                    "selected release lacks requested extras",
                    self.explanation(name),
                    tuple(self.constraints[name]),
                )
        return None


def propagate(request: Request, selected: dict[str, Release]) -> State:
    state = State()
    for root in request.roots:
        if root.marker.matches(request.target):
            state.add(root, None)
    changed = True
    while changed:
        changed = False
        for name in sorted(state.constraints):
            if name not in selected:
                continue
            release = selected[name]
            state.selected[name] = release
            features = state.extras.get(name, frozenset())
            expansion = (name, str(release.version), tuple(sorted(features)))
            if expansion in state.expansion_keys:
                continue
            state.expansion_keys.add(expansion)
            for dependency in release.dependencies:
                if dependency.marker.matches(request.target, features):
                    changed = state.add(dependency, release.identity) or changed
    return state
