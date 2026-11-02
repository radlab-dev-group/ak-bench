"""Deterministic alpha conversion for lexical bindings and cache equivalence."""

from dataclasses import replace

from . import ast
from .names import free_names
from .transform import map_children


def normalize(expression: ast.Expression) -> ast.Expression:
    counter = 0
    reserved = free_names(expression)

    def fresh():
        nonlocal counter
        while True:
            name = f"_bound_{counter}"
            counter += 1
            if name not in reserved:
                break
        return name

    def rename_pattern(pattern, names):
        if pattern.kind == "variable":
            name = fresh()
            names[pattern.name] = name
            return replace(pattern, name=name)
        return replace(
            pattern, arguments=tuple(rename_pattern(child, names) for child in pattern.arguments)
        )

    def visit(node, environment):
        if isinstance(node, ast.Variable):
            return replace(node, name=environment.get(node.name, node.name))
        if isinstance(node, ast.Lambda):
            parameter = fresh()
            return replace(
                node,
                parameter=parameter,
                body=visit(node.body, {**environment, node.parameter: parameter}),
            )
        if isinstance(node, ast.Let):
            value = visit(node.value, environment)
            name = fresh()
            return replace(
                node,
                name=name,
                value=value,
                body=visit(node.body, {**environment, node.name: name}),
            )
        if isinstance(node, ast.LetRec):
            extended = environment.copy()
            for binding in node.bindings:
                extended[binding.name] = fresh()
            bindings = tuple(
                replace(binding, name=extended[binding.name], value=visit(binding.value, extended))
                for binding in node.bindings
            )
            return replace(node, bindings=bindings, body=visit(node.body, extended))
        if isinstance(node, ast.Match):
            cases = []
            for case in node.cases:
                extended = environment.copy()
                pattern = rename_pattern(case.pattern, extended)
                cases.append(replace(case, pattern=pattern, body=visit(case.body, extended)))
            return replace(node, value=visit(node.value, environment), cases=tuple(cases))
        return map_children(node, lambda child: visit(child, environment))

    return visit(expression, {})


def equivalent(first: ast.Expression, second: ast.Expression) -> bool:
    from .syntax_codec import equivalent as syntax_equivalent

    return syntax_equivalent(normalize(first), normalize(second))
