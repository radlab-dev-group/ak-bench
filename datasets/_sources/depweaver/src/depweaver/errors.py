"""Structured unsatisfiability explanations and bounded-search termination."""

from dataclasses import dataclass

from .model import Constraint


@dataclass(frozen=True)
class Conflict:
    package: str
    reason: str
    culprits: frozenset[tuple[str, str]]
    constraints: tuple[Constraint, ...] = ()

    def document(self) -> dict:
        return {
            "package": self.package,
            "reason": self.reason,
            "culprits": [list(pair) for pair in sorted(self.culprits)],
            "constraints": [
                {"dependency": constraint.dependency.document(), "parent": constraint.parent}
                for constraint in self.constraints
            ],
        }


class Unsatisfiable(ValueError):
    def __init__(self, conflict: Conflict):
        self.conflict = conflict
        super().__init__(f"{conflict.package}: {conflict.reason}")


class SearchLimit(RuntimeError):
    pass
