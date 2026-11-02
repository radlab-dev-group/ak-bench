"""Constraint propagation, learned incompatibilities and nonchronological return."""

from dataclasses import dataclass

from .candidates import CandidateCache
from .errors import Conflict, SearchLimit, Unsatisfiable
from .learning import Learner
from .model import Request, Resolution
from .propagation import propagate
from .repository import Repository
from .trail import Trail


@dataclass
class Statistics:
    decisions: int = 0
    conflicts: int = 0
    backjumps: int = 0
    propagations: int = 0


class Resolver:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository
        self.cache = CandidateCache()
        self.learner = Learner()
        self.statistics = Statistics()

    def solve(self, request: Request) -> Resolution:
        self.learner.reset()
        self.statistics = Statistics()
        trail = Trail()

        def search():
            self.statistics.propagations += 1
            state = propagate(request, trail.selected)
            conflict = state.conflict()
            if conflict is not None:
                self.statistics.conflicts += 1
                self.learner.learn(conflict)
                return conflict
            violated = self.learner.violated(trail.identities())
            if violated is not None:
                return Conflict("<learned>", "learned incompatibility", violated)
            pending = [name for name in state.constraints if name not in state.selected]
            if not pending:
                selected = tuple(state.selected[name] for name in sorted(state.selected))
                extras = tuple(
                    (name, tuple(sorted(state.extras[name]))) for name in sorted(state.selected)
                )
                return Resolution(
                    selected,
                    extras,
                    request.target,
                    request.fingerprint,
                    self.repository.fingerprint,
                )
            domains = {
                name: self.cache.candidates(self.repository, name, state, request)
                for name in pending
            }
            name = min(pending, key=lambda item: (len(domains[item]), item))
            if not domains[name]:
                conflict = Conflict(
                    name,
                    "no eligible version satisfies active constraints",
                    state.explanation(name),
                    tuple(state.constraints[name]),
                )
                self.learner.learn(conflict)
                self.statistics.conflicts += 1
                return conflict
            original_level = trail.level
            causes = set()
            for release in domains[name]:
                self.statistics.decisions += 1
                if self.statistics.decisions > request.policy.max_decisions:
                    raise SearchLimit("decision budget exhausted")
                trail.assign(release)
                outcome = search()
                trail.rollback(original_level)
                if isinstance(outcome, Resolution):
                    return outcome
                causes.update(pair for pair in outcome.culprits if pair[0] != name)
                if release.identity not in outcome.culprits:
                    self.statistics.backjumps += 1
                    return outcome
            conflict = Conflict(
                name,
                "every eligible version leads to a conflict",
                frozenset(causes),
                tuple(state.constraints[name]),
            )
            self.learner.learn(conflict)
            return conflict

        outcome = search()
        if isinstance(outcome, Conflict):
            raise Unsatisfiable(outcome)
        return outcome
