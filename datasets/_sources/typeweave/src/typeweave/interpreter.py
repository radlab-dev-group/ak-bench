"""Lexically scoped call-by-value interpreter with explicit evaluation fuel."""

from collections.abc import Callable
from dataclasses import dataclass

from . import ast
from .diagnostics import EvaluationError
from .source import Span


@dataclass
class Cell:
    value: object


@dataclass(frozen=True)
class Variant:
    constructor: str
    fields: tuple[object, ...] = ()


@dataclass
class Closure:
    parameter: str
    body: ast.Expression
    environment: "Scope"
    constructors: dict[str, str]


@dataclass(frozen=True)
class Primitive:
    name: str
    arity: int
    function: Callable
    arguments: tuple[object, ...] = ()

    def apply(self, value: object) -> object:
        arguments = (*self.arguments, value)
        if len(arguments) == self.arity:
            return self.function(*arguments)
        return Primitive(self.name, self.arity, self.function, arguments)


class Scope:
    def __init__(self, values: dict | None = None, parent: "Scope | None" = None) -> None:
        self.values = {} if values is None else values.copy()
        self.parent = parent

    def child(self, bindings: dict | None = None) -> "Scope":
        return Scope(bindings, self)

    def get(self, name: str, span: Span) -> object:
        if name in self.values:
            value = self.values[name]
            if value is UNINITIALIZED:
                raise EvaluationError("recursive value accessed before initialization", span)
            return value
        if self.parent is not None:
            return self.parent.get(name, span)
        raise EvaluationError(f"unbound value {name}", span)


UNINITIALIZED = object()


def builtins() -> Scope:
    import operator

    operations = {
        "+": (2, operator.add),
        "-": (2, operator.sub),
        "*": (2, operator.mul),
        "/": (2, operator.floordiv),
        "<": (2, operator.lt),
        "<=": (2, operator.le),
        ">": (2, operator.gt),
        ">=": (2, operator.ge),
        "int-eq": (2, operator.eq),
        "not": (1, operator.not_),
        "and": (2, lambda first, second: first and second),
        "or": (2, lambda first, second: first or second),
        "concat": (2, operator.add),
        "strlen": (1, len),
        "show-int": (1, str),
        "string-eq": (2, operator.eq),
        "ignore": (1, lambda value: None),
    }
    scope = Scope(
        {name: Primitive(name, arity, function) for name, (arity, function) in operations.items()}
    )
    scope.values.update(
        {
            "Nil": Variant("Nil"),
            "None": Variant("None"),
            "Cons": Primitive("Cons", 2, lambda head, tail: Variant("Cons", (head, tail))),
            "Some": Primitive("Some", 1, lambda value: Variant("Some", (value,))),
        }
    )
    return scope


def match_pattern(
    pattern: ast.Pattern, value: object, canonical: dict[str, str] | None = None
) -> dict | None:
    if pattern.kind == "wildcard":
        return {}
    if pattern.kind == "variable":
        return {pattern.name: value}
    if pattern.kind == "literal":
        return {} if type(value) is type(pattern.value) and value == pattern.value else None
    if pattern.kind == "tuple":
        if not isinstance(value, tuple) or len(value) != len(pattern.arguments):
            return None
        fields = value
    else:
        name = (canonical or {}).get(pattern.name, pattern.name)
        if (
            not isinstance(value, Variant)
            or value.constructor != name
            or len(value.fields) != len(pattern.arguments)
        ):
            return None
        fields = value.fields
    bindings = {}
    for child, item in zip(pattern.arguments, fields, strict=True):
        found = match_pattern(child, item, canonical)
        if found is None:
            return None
        if bindings.keys() & found.keys():
            raise EvaluationError("duplicate pattern variable", child.span)
        bindings.update(found)
    return bindings


class Interpreter:
    def __init__(self, *, fuel: int = 100_000, constructors: dict[str, str] | None = None) -> None:
        if type(fuel) is not int or fuel < 1:
            raise ValueError("fuel must be a positive integer")
        self.fuel = fuel
        self.constructors = constructors or {}

    def evaluate(self, expression: ast.Expression, scope: Scope | None = None) -> object:
        scope = builtins() if scope is None else scope
        self.fuel -= 1
        if self.fuel < 0:
            raise EvaluationError("evaluation fuel exhausted", expression.span)
        if isinstance(expression, ast.Literal):
            return expression.value
        if isinstance(expression, ast.Variable):
            return scope.get(expression.name, expression.span)
        if isinstance(expression, ast.Lambda):
            return Closure(expression.parameter, expression.body, scope, self.constructors.copy())
        if isinstance(expression, ast.Apply):
            function = self.evaluate(expression.function, scope)
            argument = self.evaluate(expression.argument, scope)
            return self.apply(function, argument, expression.span)
        if isinstance(expression, ast.Let):
            value = self.evaluate(expression.value, scope)
            return self.evaluate(expression.body, scope.child({expression.name: value}))
        if isinstance(expression, ast.LetRec):
            child = scope.child(
                dict.fromkeys((binding.name for binding in expression.bindings), UNINITIALIZED)
            )
            from .names import components

            for group in components(expression.bindings):
                for binding in group:
                    child.values[binding.name] = self.evaluate(binding.value, child)
            return self.evaluate(expression.body, child)
        if isinstance(expression, ast.If):
            condition = self.evaluate(expression.condition, scope)
            if type(condition) is not bool:
                raise EvaluationError("condition is not Bool", expression.condition.span)
            return self.evaluate(
                expression.consequent if condition else expression.alternative, scope
            )
        if isinstance(expression, ast.TupleExpr):
            return tuple(self.evaluate(item, scope) for item in expression.items)
        if isinstance(expression, ast.Ref):
            return Cell(self.evaluate(expression.value, scope))
        if isinstance(expression, ast.Deref):
            cell = self.evaluate(expression.reference, scope)
            if not isinstance(cell, Cell):
                raise EvaluationError("get expects Ref", expression.span)
            return cell.value
        if isinstance(expression, ast.Assign):
            cell = self.evaluate(expression.reference, scope)
            value = self.evaluate(expression.value, scope)
            if not isinstance(cell, Cell):
                raise EvaluationError("set expects Ref", expression.span)
            cell.value = value
            return None
        if isinstance(expression, ast.Sequence):
            value = None
            for item in expression.items:
                value = self.evaluate(item, scope)
            return value
        if isinstance(expression, ast.Annotate):
            return self.evaluate(expression.value, scope)
        if isinstance(expression, ast.Match):
            value = self.evaluate(expression.value, scope)
            for case in expression.cases:
                bindings = match_pattern(case.pattern, value, self.constructors)
                if bindings is not None:
                    return self.evaluate(case.body, scope.child(bindings))
            raise EvaluationError("unmatched value", expression.span)
        raise EvaluationError("unknown expression", expression.span)

    def apply(self, function: object, argument: object, span: Span) -> object:
        if isinstance(function, Closure):
            previous = self.constructors
            self.constructors = function.constructors
            try:
                return self.evaluate(
                    function.body, function.environment.child({function.parameter: argument})
                )
            finally:
                self.constructors = previous
        if isinstance(function, Primitive):
            try:
                return function.apply(argument)
            except (TypeError, ValueError, ZeroDivisionError) as error:
                raise EvaluationError(str(error), span) from error
        raise EvaluationError("attempt to call a non-function", span)


def data_scope(module: ast.Module, scope: Scope) -> dict[str, str]:
    canonical = {}
    for declaration in module.data:
        for constructor in declaration.constructors:
            qualified = module.name + "." + constructor.name
            canonical[constructor.name] = qualified
            arity = len(constructor.fields)
            if arity == 0:
                scope.values[constructor.name] = Variant(qualified)
            else:

                def build(*arguments, tag=qualified):
                    return Variant(tag, tuple(arguments))

                scope.values[constructor.name] = Primitive(qualified, arity, build)
    return canonical


def to_document(value: object) -> object:
    if value is None or type(value) in {bool, int, str}:
        return value
    if isinstance(value, tuple):
        return {"tuple": [to_document(item) for item in value]}
    if isinstance(value, Variant):
        return {
            "constructor": value.constructor,
            "fields": [to_document(item) for item in value.fields],
        }
    if isinstance(value, Cell):
        return {"reference": to_document(value.value)}
    if isinstance(value, (Closure, Primitive)):
        return {"function": True}
    raise TypeError("unknown runtime value")
