"""Implement Algorithm W, SCC binding groups and conservative value restriction.

The full language and error contract is in SPEC.md. The AST, runtime and
prelude are working. All recursive SCC members are monomorphic while their
right-hand sides are inferred; completed dependency SCCs may be generalized.
Only nonexpansive RHSs generalize. Recursive RHSs must be lambdas.
"""

from dataclasses import dataclass

from . import ast
from .environment import Environment
from .types import Scheme, Type
from .unification import Solver


@dataclass(frozen=True)
class Inference:
    type: Type
    bindings: dict[str, Scheme]


class Inferencer:
    def __init__(self, solver: Solver | None = None) -> None:
        self.solver = solver or Solver()
        self.coverage_obligations: list = []

    def expression(self, expression: ast.Expression, environment: Environment) -> Type:
        raise NotImplementedError(
            "infer all expression forms and collect deferred coverage obligations"
        )

    def group(self, bindings: tuple[ast.Binding, ...], environment: Environment) -> Environment:
        raise NotImplementedError("infer SCCs in dependency order without polymorphic recursion")

    def pattern(
        self, pattern: ast.Pattern, expected: Type, environment: Environment
    ) -> dict[str, Scheme]:
        raise NotImplementedError(
            "infer patterns, checking constructor arity and duplicate bindings"
        )

    def finish(self) -> None:
        raise NotImplementedError("normalize and discharge every pattern coverage obligation")
