"""Capture-aware syntax transformation and conservative constant folding."""

from collections.abc import Callable
from dataclasses import replace

from . import ast
from .names import free_names


def map_children(node: ast.Expression, transform: Callable) -> ast.Expression:
    if isinstance(node, (ast.Literal, ast.Variable)):
        return node
    if isinstance(node, ast.Lambda):
        return replace(node, body=transform(node.body))
    if isinstance(node, ast.Apply):
        return replace(node, function=transform(node.function), argument=transform(node.argument))
    if isinstance(node, ast.Let):
        return replace(node, value=transform(node.value), body=transform(node.body))
    if isinstance(node, ast.LetRec):
        return replace(
            node,
            bindings=tuple(
                replace(binding, value=transform(binding.value)) for binding in node.bindings
            ),
            body=transform(node.body),
        )
    if isinstance(node, ast.If):
        return replace(
            node,
            condition=transform(node.condition),
            consequent=transform(node.consequent),
            alternative=transform(node.alternative),
        )
    if isinstance(node, (ast.TupleExpr, ast.Sequence)):
        return replace(node, items=tuple(transform(item) for item in node.items))
    if isinstance(node, (ast.Ref, ast.Annotate)):
        return replace(node, value=transform(node.value))
    if isinstance(node, ast.Deref):
        return replace(node, reference=transform(node.reference))
    if isinstance(node, ast.Assign):
        return replace(node, reference=transform(node.reference), value=transform(node.value))
    if isinstance(node, ast.Match):
        return replace(
            node,
            value=transform(node.value),
            cases=tuple(replace(case, body=transform(case.body)) for case in node.cases),
        )
    raise TypeError(type(node).__name__)


def substitute(node: ast.Expression, name: str, value: ast.Expression) -> ast.Expression:
    if isinstance(node, ast.Variable):
        return value if node.name == name else node
    if isinstance(node, ast.Lambda):
        if node.parameter == name:
            return node
        if node.parameter in free_names(value) and name in free_names(node.body):
            raise ValueError("substitution would capture a free variable")
        return replace(node, body=substitute(node.body, name, value))
    if isinstance(node, ast.Let):
        first = substitute(node.value, name, value)
        if node.name == name:
            return replace(node, value=first)
        if node.name in free_names(value) and name in free_names(node.body):
            raise ValueError("substitution would capture a free variable")
        return replace(node, value=first, body=substitute(node.body, name, value))
    if isinstance(node, ast.LetRec):
        bound = {binding.name for binding in node.bindings}
        if name in bound:
            return node
        if bound & free_names(value) and name in free_names(node):
            raise ValueError("substitution would capture a recursive binding")
    if isinstance(node, ast.Match):
        cases = []
        for case in node.cases:
            bound = set(ast.pattern_names(case.pattern))
            if name in bound:
                cases.append(case)
            else:
                if bound & free_names(value) and name in free_names(case.body):
                    raise ValueError("substitution would capture a pattern binding")
                cases.append(replace(case, body=substitute(case.body, name, value)))
        return replace(node, value=substitute(node.value, name, value), cases=tuple(cases))
    return map_children(node, lambda child: substitute(child, name, value))


def pure(node: ast.Expression) -> bool:
    if isinstance(node, (ast.Literal, ast.Variable, ast.Lambda)):
        return True
    if isinstance(node, ast.TupleExpr):
        return all(pure(item) for item in node.items)
    if isinstance(node, ast.Annotate):
        return pure(node.value)
    return False


def fold(node: ast.Expression) -> ast.Expression:
    node = map_children(node, fold)
    if (
        isinstance(node, ast.If)
        and isinstance(node.condition, ast.Literal)
        and type(node.condition.value) is bool
    ):
        return node.consequent if node.condition.value else node.alternative
    if isinstance(node, ast.Let) and isinstance(node.value, ast.Literal):
        return fold(substitute(node.body, node.name, node.value))
    if isinstance(node, ast.Sequence):
        items = tuple(item for item in node.items[:-1] if not pure(item)) + node.items[-1:]
        return items[0] if len(items) == 1 else replace(node, items=items)
    return node


def erase_annotations(node: ast.Expression) -> ast.Expression:
    if isinstance(node, ast.Annotate):
        return erase_annotations(node.value)
    return map_children(node, erase_annotations)
