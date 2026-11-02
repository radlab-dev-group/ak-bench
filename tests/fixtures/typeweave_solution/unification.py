"""Reference substitution solver, excluded from every agent workspace."""

from .diagnostics import CompileError, Related
from .source import Span
from .types import Constructor, Scheme, Type, Variable, free_variables, render, replace


class Solver:
    def __init__(self) -> None:
        self.next_identity = 100
        self.substitutions: dict[int, Type] = {}

    def fresh(self) -> Variable:
        result = Variable(self.next_identity)
        self.next_identity += 1
        return result

    def apply(self, term: Type) -> Type:
        if isinstance(term, Variable):
            replacement = self.substitutions.get(term.identity)
            if replacement is None:
                return term
            normalized = self.apply(replacement)
            self.substitutions[term.identity] = normalized
            return normalized
        return Constructor(term.name, tuple(self.apply(argument) for argument in term.arguments))

    def unify(self, first: Type, second: Type, span: Span, origin: Span | None = None) -> None:
        first, second = self.apply(first), self.apply(second)
        if first == second:
            return
        if isinstance(second, Variable) and not isinstance(first, Variable):
            first, second = second, first
        related = (Related("constraint originates here", origin),) if origin else ()
        if isinstance(first, Variable):
            if first.identity in free_variables(second):
                raise CompileError(
                    "infinite-type", "type variable occurs inside its own type", span, related
                )
            self.substitutions[first.identity] = second
            return
        if first.name != second.name or len(first.arguments) != len(second.arguments):
            raise CompileError(
                "type-mismatch",
                f"cannot unify {render(first)} with {render(second)}",
                span,
                related,
            )
        for left, right in zip(first.arguments, second.arguments, strict=True):
            self.unify(left, right, span, origin)

    def instantiate(self, scheme: Scheme) -> Type:
        return self.apply(
            replace(scheme.body, {identity: self.fresh() for identity in scheme.quantified})
        )

    def generalize(self, term: Type, environment, *, allow: bool = True) -> Scheme:
        term = self.apply(term)
        free = set()
        for scheme in environment.values.values():
            masked = {
                identity: value
                for identity, value in self.substitutions.items()
                if identity not in scheme.quantified
            }
            normalized = replace(scheme.body, masked)
            free.update(free_variables(self.apply(normalized)) - set(scheme.quantified))
        quantified = tuple(sorted(free_variables(term) - free)) if allow else ()
        return Scheme(quantified, term)
