"""Lexical type environments; extension never mutates an enclosing scope."""

from dataclasses import dataclass, field

from . import ast
from .diagnostics import CompileError
from .source import Span
from .types import Scheme


@dataclass(frozen=True)
class DataInfo:
    name: str
    parameters: tuple[int, ...]
    constructors: tuple[str, ...]


@dataclass(frozen=True)
class ConstructorInfo:
    name: str
    owner: str
    scheme: Scheme
    arity: int


@dataclass
class Environment:
    values: dict[str, Scheme] = field(default_factory=dict)
    data: dict[str, DataInfo] = field(default_factory=dict)
    constructors: dict[str, ConstructorInfo] = field(default_factory=dict)

    def extend(self, bindings: dict[str, Scheme]) -> "Environment":
        return Environment({**self.values, **bindings}, self.data.copy(), self.constructors.copy())

    def lookup(self, name: str, span: Span) -> Scheme:
        if name not in self.values:
            raise CompileError("unbound-name", f"unbound name: {name}", span)
        return self.values[name]

    def constructor(self, name: str, span: Span) -> ConstructorInfo:
        if name not in self.constructors:
            raise CompileError("unknown-constructor", f"unknown constructor: {name}", span)
        return self.constructors[name]

    def without(self, names: set[str]) -> "Environment":
        return Environment(
            {key: value for key, value in self.values.items() if key not in names},
            self.data.copy(),
            self.constructors.copy(),
        )


def nonexpansive(expression: ast.Expression) -> bool:
    if isinstance(expression, (ast.Literal, ast.Variable, ast.Lambda)):
        return True
    if isinstance(expression, ast.TupleExpr):
        return all(nonexpansive(item) for item in expression.items)
    if isinstance(expression, ast.Annotate):
        return nonexpansive(expression.value)
    return False
