"""Portable AST serialization for caches, bytecode patterns and editor tooling."""

from dataclasses import fields

from . import ast
from .source import Position, Span

NODES = {
    kind.__name__: kind
    for kind in (
        ast.Literal,
        ast.Variable,
        ast.Lambda,
        ast.Apply,
        ast.Let,
        ast.LetRec,
        ast.Binding,
        ast.If,
        ast.TupleExpr,
        ast.Ref,
        ast.Deref,
        ast.Assign,
        ast.Sequence,
        ast.Annotate,
        ast.Pattern,
        ast.Case,
        ast.Match,
        ast.TypeSyntax,
        ast.Constructor,
        ast.Data,
        ast.Import,
        ast.Module,
    )
}
TUPLE_FIELDS = {
    "bindings",
    "items",
    "arguments",
    "cases",
    "fields",
    "parameters",
    "constructors",
    "imports",
    "data",
    "definitions",
    "exports",
}


def encode(node: ast.Node) -> dict:
    document = {"node": type(node).__name__}
    for field in fields(node):
        value = getattr(node, field.name)
        if isinstance(value, Span):
            document[field.name] = value.document()
        elif isinstance(value, ast.Node):
            document[field.name] = encode(value)
        elif isinstance(value, tuple):
            document[field.name] = [
                encode(item) if isinstance(item, ast.Node) else item for item in value
            ]
        else:
            document[field.name] = value
    return document


def decode_span(document: dict) -> Span:
    if not isinstance(document, dict) or set(document) != {"source", "start", "end"}:
        raise ValueError("invalid source span")
    if not isinstance(document["source"], str):
        raise ValueError("invalid source name")
    positions = []
    for key in ("start", "end"):
        coordinates = document[key]
        if not isinstance(coordinates, dict) or set(coordinates) != {"offset", "line", "column"}:
            raise ValueError("invalid source position")
        if any(type(value) is not int for value in coordinates.values()):
            raise ValueError("non-integer source position")
        if coordinates["offset"] < 0 or coordinates["line"] < 1 or coordinates["column"] < 1:
            raise ValueError("negative source position")
        positions.append(Position(**coordinates))
    if positions[1].offset < positions[0].offset:
        raise ValueError("inverted source span")
    return Span(document["source"], *positions)


def decode(document: dict, *, depth: int = 0) -> ast.Node:
    if depth > 500 or not isinstance(document, dict):
        raise ValueError("invalid AST document")
    kind = NODES.get(document.get("node"))
    if kind is None:
        raise ValueError("unknown AST node")
    expected = {field.name for field in fields(kind)} | {"node"}
    if set(document) != expected:
        raise ValueError("AST field mismatch")
    arguments = {}
    for field in fields(kind):
        value = document[field.name]
        if field.name == "span":
            arguments[field.name] = decode_span(value)
        elif isinstance(value, dict) and "node" in value:
            arguments[field.name] = decode(value, depth=depth + 1)
        elif field.name in TUPLE_FIELDS:
            if not isinstance(value, list):
                raise ValueError("expected AST sequence")
            arguments[field.name] = tuple(
                decode(item, depth=depth + 1) if isinstance(item, dict) else item for item in value
            )
        else:
            arguments[field.name] = value
    return kind(**arguments)


def without_spans(document: object) -> object:
    if isinstance(document, dict):
        return {key: without_spans(value) for key, value in document.items() if key != "span"}
    if isinstance(document, list):
        return [without_spans(item) for item in document]
    return document


def equivalent(first: ast.Node, second: ast.Node) -> bool:
    return without_spans(encode(first)) == without_spans(encode(second))
