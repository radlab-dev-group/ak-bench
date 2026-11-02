"""Implement substitution normalization, occurs-check and provenance-aware unification.

Fresh variables start at identity 100. apply recursively follows substitutions;
never capture quantified variables when substituting a Scheme. On mismatch use
CompileError('type-mismatch', ..., span), and on self occurrence 'infinite-type'.
Every mismatch needs the current constraint span and an optional Related origin.
"""

from .source import Span
from .types import Scheme, Type, Variable


class Solver:
    def __init__(self) -> None:
        self.next_identity = 100
        self.substitutions: dict[int, Type] = {}

    def fresh(self) -> Variable:
        result = Variable(self.next_identity)
        self.next_identity += 1
        return result

    def apply(self, term: Type) -> Type:
        raise NotImplementedError("normalize transitive substitutions")

    def unify(self, first: Type, second: Type, span: Span, origin: Span | None = None) -> None:
        raise NotImplementedError("unify with occurs-check and source provenance")

    def instantiate(self, scheme: Scheme) -> Type:
        raise NotImplementedError("freshen only quantified variables")

    def generalize(self, term: Type, environment, *, allow: bool = True) -> Scheme:
        raise NotImplementedError(
            "quantify normalized free variables absent from normalized environment"
        )
