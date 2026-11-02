"""Implement typed pattern-matrix usefulness and exhaustiveness.

Handle nested algebraic constructors, tuples, Bool and Unit as finite domains;
Int and String are infinite domains. A missing wildcard on an infinite domain
is not exhaustive. A row is redundant iff it adds no value to earlier rows.
Constructor aliases must compare by canonical ConstructorInfo.name.
Report 'redundant-pattern' at that case and 'non-exhaustive' at the match.
Do not bound recursive types by an arbitrary finite enumeration depth.
"""

from . import ast
from .environment import Environment
from .types import Type


def check(match: ast.Match, subject: Type, environment: Environment, solver) -> None:
    raise NotImplementedError("matrix specialization/defaulting over normalized types")
