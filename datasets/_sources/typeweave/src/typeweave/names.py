"""Lexical free-variable analysis and deterministic dependency components."""

from . import ast
from .diagnostics import CompileError


def free_names(expression: ast.Expression, bound: frozenset[str] = frozenset()) -> set[str]:
    if isinstance(expression, ast.Variable):
        return set() if expression.name in bound else {expression.name}
    if isinstance(expression, ast.Lambda):
        return free_names(expression.body, bound | {expression.parameter})
    if isinstance(expression, ast.Let):
        return free_names(expression.value, bound) | free_names(
            expression.body, bound | {expression.name}
        )
    if isinstance(expression, ast.LetRec):
        extended = bound | {binding.name for binding in expression.bindings}
        result = free_names(expression.body, extended)
        for binding in expression.bindings:
            result |= free_names(binding.value, extended)
        return result
    if isinstance(expression, ast.Match):
        result = free_names(expression.value, bound)
        for case in expression.cases:
            result |= free_names(case.body, bound | set(ast.pattern_names(case.pattern)))
            result |= constructor_names(case.pattern)
        return result
    result = set()
    for child in ast.children(expression):
        result |= free_names(child, bound)
    return result


def constructor_names(pattern: ast.Pattern) -> set[str]:
    result = {pattern.name} if pattern.kind == "constructor" else set()
    for child in pattern.arguments:
        result |= constructor_names(child)
    return result


def components(bindings: tuple[ast.Binding, ...]) -> tuple[tuple[ast.Binding, ...], ...]:
    by_name = {binding.name: binding for binding in bindings}
    if len(by_name) != len(bindings):
        raise CompileError("duplicate-binding", "duplicate definition", bindings[0].span)
    edges = {name: free_names(binding.value) & by_name.keys() for name, binding in by_name.items()}
    counter = 0
    indices, lowlinks = {}, {}
    stack, on_stack, result = [], set(), []

    def visit(name: str) -> None:
        nonlocal counter
        indices[name] = lowlinks[name] = counter
        counter += 1
        stack.append(name)
        on_stack.add(name)
        for dependency in sorted(edges[name]):
            if dependency not in indices:
                visit(dependency)
                lowlinks[name] = min(lowlinks[name], lowlinks[dependency])
            elif dependency in on_stack:
                lowlinks[name] = min(lowlinks[name], indices[dependency])
        if lowlinks[name] == indices[name]:
            group = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                group.append(by_name[member])
                if member == name:
                    break
            result.append(tuple(sorted(group, key=lambda binding: binding.name)))

    for name in sorted(by_name):
        if name not in indices:
            visit(name)
    return tuple(result)


def check_names(expression: ast.Expression, available: set[str]) -> None:
    missing = free_names(expression) - available
    if missing:
        raise CompileError("unbound-name", f"unbound name: {min(missing)}", expression.span)
