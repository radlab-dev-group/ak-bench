"""Implement data declaration registration and annotation elaboration.

Data types are nominal: locally declared names become Module.Type. Predeclare
all data arities before elaborating constructor fields, allowing mutually
recursive data. Quantify constructor parameters independently of value types.
Reject duplicate parameters/types/constructors and unbound annotation variables.
Expression annotation lowercase variables are fresh per annotation occurrence.
"""

from . import ast
from .environment import Environment
from .types import Type


def annotation(
    syntax: ast.TypeSyntax, environment: Environment, solver, variables: dict | None = None
) -> Type:
    raise NotImplementedError("resolve annotation names, parameters and arities")


def register(module: ast.Module, environment: Environment, solver) -> Environment:
    raise NotImplementedError("register nominal mutually recursive data declarations")
