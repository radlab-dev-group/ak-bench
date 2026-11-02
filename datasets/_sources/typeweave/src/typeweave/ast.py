"""Public immutable syntax tree, independent of type inference state."""

from dataclasses import dataclass

from .source import Span


@dataclass(frozen=True)
class Node:
    span: Span


@dataclass(frozen=True)
class Literal(Node):
    value: int | bool | str | None


@dataclass(frozen=True)
class Variable(Node):
    name: str


@dataclass(frozen=True)
class Lambda(Node):
    parameter: str
    body: "Expression"


@dataclass(frozen=True)
class Apply(Node):
    function: "Expression"
    argument: "Expression"


@dataclass(frozen=True)
class Let(Node):
    name: str
    value: "Expression"
    body: "Expression"


@dataclass(frozen=True)
class Binding(Node):
    name: str
    value: "Expression"


@dataclass(frozen=True)
class LetRec(Node):
    bindings: tuple[Binding, ...]
    body: "Expression"


@dataclass(frozen=True)
class If(Node):
    condition: "Expression"
    consequent: "Expression"
    alternative: "Expression"


@dataclass(frozen=True)
class TupleExpr(Node):
    items: tuple["Expression", ...]


@dataclass(frozen=True)
class Ref(Node):
    value: "Expression"


@dataclass(frozen=True)
class Deref(Node):
    reference: "Expression"


@dataclass(frozen=True)
class Assign(Node):
    reference: "Expression"
    value: "Expression"


@dataclass(frozen=True)
class Sequence(Node):
    items: tuple["Expression", ...]


@dataclass(frozen=True)
class Annotate(Node):
    value: "Expression"
    annotation: "TypeSyntax"


@dataclass(frozen=True)
class Pattern(Node):
    kind: str
    name: str = ""
    value: int | bool | str | None = None
    arguments: tuple["Pattern", ...] = ()


@dataclass(frozen=True)
class Case(Node):
    pattern: Pattern
    body: "Expression"


@dataclass(frozen=True)
class Match(Node):
    value: "Expression"
    cases: tuple[Case, ...]


@dataclass(frozen=True)
class TypeSyntax(Node):
    name: str
    arguments: tuple["TypeSyntax", ...] = ()


@dataclass(frozen=True)
class Constructor(Node):
    name: str
    fields: tuple[TypeSyntax, ...]


@dataclass(frozen=True)
class Data(Node):
    name: str
    parameters: tuple[str, ...]
    constructors: tuple[Constructor, ...]


@dataclass(frozen=True)
class Import(Node):
    module: str
    alias: str


@dataclass(frozen=True)
class Module(Node):
    name: str
    imports: tuple[Import, ...]
    data: tuple[Data, ...]
    definitions: tuple[Binding, ...]
    exports: tuple[str, ...]


Expression = (
    Literal
    | Variable
    | Lambda
    | Apply
    | Let
    | LetRec
    | If
    | TupleExpr
    | Ref
    | Deref
    | Assign
    | Sequence
    | Annotate
    | Match
)


def children(expression: Expression) -> tuple[Expression, ...]:
    if isinstance(expression, (Literal, Variable)):
        return ()
    if isinstance(expression, Lambda):
        return (expression.body,)
    if isinstance(expression, Apply):
        return expression.function, expression.argument
    if isinstance(expression, Let):
        return expression.value, expression.body
    if isinstance(expression, LetRec):
        return (*(binding.value for binding in expression.bindings), expression.body)
    if isinstance(expression, If):
        return expression.condition, expression.consequent, expression.alternative
    if isinstance(expression, (TupleExpr, Sequence)):
        return expression.items
    if isinstance(expression, (Ref, Annotate)):
        return (expression.value,)
    if isinstance(expression, Deref):
        return (expression.reference,)
    if isinstance(expression, Assign):
        return expression.reference, expression.value
    if isinstance(expression, Match):
        return (expression.value, *(case.body for case in expression.cases))
    raise TypeError(type(expression).__name__)


def walk(expression: Expression):
    yield expression
    for child in children(expression):
        yield from walk(child)


def pattern_names(pattern: Pattern) -> tuple[str, ...]:
    own = (pattern.name,) if pattern.kind == "variable" else ()
    return own + tuple(name for child in pattern.arguments for name in pattern_names(child))
