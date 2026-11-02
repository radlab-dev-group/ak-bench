"""Validate externally supplied ASTs before compiler/editor consumption."""

from dataclasses import fields

from . import ast
from .source import Span

EXPRESSIONS = (
    ast.Literal,
    ast.Variable,
    ast.Lambda,
    ast.Apply,
    ast.Let,
    ast.LetRec,
    ast.If,
    ast.TupleExpr,
    ast.Ref,
    ast.Deref,
    ast.Assign,
    ast.Sequence,
    ast.Annotate,
    ast.Match,
)


def validate(root: ast.Node, *, max_nodes: int = 100_000, max_depth: int = 500) -> None:
    visited = 0
    active = set()

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    def name(value):
        require(isinstance(value, str) and bool(value), "AST name must be nonempty")

    def expression(value):
        require(isinstance(value, EXPRESSIONS), "expected expression node")

    def sequence(value, kind):
        require(
            isinstance(value, tuple) and all(isinstance(item, kind) for item in value),
            "invalid AST sequence",
        )

    def visit(node, depth):
        nonlocal visited
        require(isinstance(node, ast.Node), "expected AST node")
        visited += 1
        require(visited <= max_nodes and depth <= max_depth, "AST resource limit exceeded")
        require(id(node) not in active, "cyclic AST object")
        active.add(id(node))
        require(isinstance(node.span, Span), "invalid AST span")
        require(node.span.start.offset <= node.span.end.offset, "inverted AST span")
        if isinstance(node, ast.Literal):
            require(
                node.value is None or type(node.value) in {int, bool, str},
                "unsupported literal value",
            )
        elif isinstance(node, ast.Variable):
            name(node.name)
        elif isinstance(node, ast.Lambda):
            name(node.parameter)
            expression(node.body)
        elif isinstance(node, ast.Apply):
            expression(node.function)
            expression(node.argument)
        elif isinstance(node, ast.Let):
            name(node.name)
            expression(node.value)
            expression(node.body)
        elif isinstance(node, ast.Binding):
            name(node.name)
            expression(node.value)
        elif isinstance(node, ast.LetRec):
            sequence(node.bindings, ast.Binding)
            require(bool(node.bindings), "empty recursive binding group")
            require(
                len({binding.name for binding in node.bindings}) == len(node.bindings),
                "duplicate recursive definition",
            )
            expression(node.body)
        elif isinstance(node, ast.If):
            expression(node.condition)
            expression(node.consequent)
            expression(node.alternative)
        elif isinstance(node, (ast.TupleExpr, ast.Sequence)):
            sequence(node.items, EXPRESSIONS)
            if isinstance(node, ast.Sequence):
                require(bool(node.items), "empty sequencing expression")
        elif isinstance(node, ast.Ref):
            expression(node.value)
        elif isinstance(node, ast.Deref):
            expression(node.reference)
        elif isinstance(node, ast.Assign):
            expression(node.reference)
            expression(node.value)
        elif isinstance(node, ast.Annotate):
            expression(node.value)
            require(isinstance(node.annotation, ast.TypeSyntax), "invalid annotation syntax")
        elif isinstance(node, ast.Pattern):
            require(
                node.kind in {"wildcard", "variable", "literal", "tuple", "constructor"},
                "unknown pattern kind",
            )
            sequence(node.arguments, ast.Pattern)
            if node.kind in {"variable", "constructor"}:
                name(node.name)
            if node.kind in {"wildcard", "variable", "literal"}:
                require(not node.arguments, "atomic pattern has arguments")
            if node.kind == "literal":
                require(
                    node.value is None or type(node.value) in {int, bool, str},
                    "invalid pattern literal",
                )
            names = ast.pattern_names(node)
            require(len(set(names)) == len(names), "duplicate pattern binding")
        elif isinstance(node, ast.Case):
            require(isinstance(node.pattern, ast.Pattern), "case has invalid pattern")
            expression(node.body)
        elif isinstance(node, ast.Match):
            expression(node.value)
            sequence(node.cases, ast.Case)
            require(bool(node.cases), "match has no cases")
        elif isinstance(node, ast.TypeSyntax):
            name(node.name)
            sequence(node.arguments, ast.TypeSyntax)
        elif isinstance(node, ast.Constructor):
            name(node.name)
            sequence(node.fields, ast.TypeSyntax)
        elif isinstance(node, ast.Data):
            name(node.name)
            sequence(node.parameters, str)
            require(len(set(node.parameters)) == len(node.parameters), "duplicate type parameter")
            for parameter in node.parameters:
                name(parameter)
            sequence(node.constructors, ast.Constructor)
            require(bool(node.constructors), "data type has no constructors")
        elif isinstance(node, ast.Import):
            name(node.module)
            name(node.alias)
        elif isinstance(node, ast.Module):
            name(node.name)
            sequence(node.imports, ast.Import)
            sequence(node.data, ast.Data)
            sequence(node.definitions, ast.Binding)
            sequence(node.exports, str)
            for exported in node.exports:
                name(exported)
        else:
            raise ValueError("unknown AST node class")
        for field in fields(node):
            value = getattr(node, field.name)
            if isinstance(value, ast.Node):
                visit(value, depth + 1)
            elif isinstance(value, tuple):
                for item in value:
                    if isinstance(item, ast.Node):
                        visit(item, depth + 1)
        active.remove(id(node))

    if type(max_nodes) is not int or type(max_depth) is not int or min(max_nodes, max_depth) < 1:
        raise ValueError("invalid AST validation budget")
    visit(root, 1)


def size(root: ast.Node) -> tuple[int, int]:
    count, maximum = 0, 0

    def visit(node, depth):
        nonlocal count, maximum
        count += 1
        maximum = max(maximum, depth)
        for field in fields(node):
            value = getattr(node, field.name)
            if isinstance(value, ast.Node):
                visit(value, depth + 1)
            elif isinstance(value, tuple):
                for item in value:
                    if isinstance(item, ast.Node):
                        visit(item, depth + 1)

    validate(root)
    visit(root, 1)
    return count, maximum
