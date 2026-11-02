"""Stable source formatting; formatted trees can be parsed again."""

import json

from . import ast


def literal(value: object) -> str:
    if value is None:
        return "unit"
    if type(value) is bool:
        return "true" if value else "false"
    return json.dumps(value, ensure_ascii=False)


def type_syntax(syntax: ast.TypeSyntax) -> str:
    if not syntax.arguments:
        return syntax.name
    return "(" + " ".join((syntax.name, *(type_syntax(item) for item in syntax.arguments))) + ")"


def pattern(node: ast.Pattern) -> str:
    if node.kind == "wildcard":
        return "_"
    if node.kind == "variable":
        return node.name
    if node.kind == "literal":
        return literal(node.value)
    head = "tuple" if node.kind == "tuple" else node.name
    if not node.arguments and node.kind == "constructor":
        return head
    return "(" + " ".join((head, *(pattern(item) for item in node.arguments))) + ")"


def expression(node: ast.Expression) -> str:
    if isinstance(node, ast.Literal):
        return literal(node.value)
    if isinstance(node, ast.Variable):
        return node.name
    if isinstance(node, ast.Lambda):
        return f"(fn {node.parameter} {expression(node.body)})"
    if isinstance(node, ast.Apply):
        return f"({expression(node.function)} {expression(node.argument)})"
    if isinstance(node, ast.Let):
        return f"(let {node.name} {expression(node.value)} {expression(node.body)})"
    if isinstance(node, ast.LetRec):
        bindings = " ".join(
            f"({binding.name} {expression(binding.value)})" for binding in node.bindings
        )
        return f"(letrec ({bindings}) {expression(node.body)})"
    if isinstance(node, ast.If):
        return (
            f"(if {expression(node.condition)} {expression(node.consequent)} "
            f"{expression(node.alternative)})"
        )
    if isinstance(node, ast.TupleExpr):
        return "(tuple" + "".join(" " + expression(item) for item in node.items) + ")"
    if isinstance(node, ast.Ref):
        return f"(ref {expression(node.value)})"
    if isinstance(node, ast.Deref):
        return f"(get {expression(node.reference)})"
    if isinstance(node, ast.Assign):
        return f"(set {expression(node.reference)} {expression(node.value)})"
    if isinstance(node, ast.Sequence):
        return "(do " + " ".join(expression(item) for item in node.items) + ")"
    if isinstance(node, ast.Annotate):
        return f"(ann {expression(node.value)} {type_syntax(node.annotation)})"
    if isinstance(node, ast.Match):
        cases = " ".join(
            f"({pattern(case.pattern)} {expression(case.body)})" for case in node.cases
        )
        return f"(match {expression(node.value)} {cases})"
    raise TypeError(type(node).__name__)


def module(node: ast.Module) -> str:
    lines = [f"(module {node.name}"]
    for imported in node.imports:
        lines.append(f"  (import {imported.module} {imported.alias})")
    for declaration in node.data:
        constructors = []
        for constructor in declaration.constructors:
            fields = "".join(" " + type_syntax(field) for field in constructor.fields)
            constructors.append(f"({constructor.name}{fields})")
        lines.append(
            f"  (data {declaration.name} ({' '.join(declaration.parameters)}) "
            f"{' '.join(constructors)})"
        )
    for definition in node.definitions:
        lines.append(f"  (def {definition.name} {expression(definition.value)})")
    if node.exports:
        lines.append("  (export " + " ".join(node.exports) + ")")
    return "\n".join(lines) + ")\n"
