"""Conservative effect and call analyses used by compiler diagnostics/tooling."""

from dataclasses import dataclass
from enum import IntFlag

from . import ast
from .names import free_names
from .source import Span


class Effect(IntFlag):
    PURE = 0
    ALLOCATE = 1
    READ = 2
    WRITE = 4
    CALL = 8
    DIVERGE = 16


def effects(expression: ast.Expression) -> Effect:
    if isinstance(expression, (ast.Literal, ast.Variable, ast.Lambda)):
        return Effect.PURE
    result = Effect.PURE
    for child in ast.children(expression):
        result |= effects(child)
    if isinstance(expression, ast.Ref):
        result |= Effect.ALLOCATE
    elif isinstance(expression, ast.Deref):
        result |= Effect.READ
    elif isinstance(expression, ast.Assign):
        result |= Effect.WRITE
    elif isinstance(expression, ast.Apply):
        result |= Effect.CALL | Effect.DIVERGE
    elif isinstance(expression, ast.LetRec):
        result |= Effect.DIVERGE
    return result


@dataclass(frozen=True)
class CallSite:
    caller: str
    callee: str | None
    span: Span
    tail: bool


def calls(expression: ast.Expression, caller: str = "<expression>") -> tuple[CallSite, ...]:
    result = []

    def visit(node, current, tail):
        if isinstance(node, ast.Apply):
            function = node.function
            while isinstance(function, ast.Apply):
                function = function.function
            callee = function.name if isinstance(function, ast.Variable) else None
            result.append(CallSite(current, callee, node.span, tail))
            visit(node.function, current, False)
            visit(node.argument, current, False)
        elif isinstance(node, ast.Lambda):
            visit(node.body, current, True)
        elif isinstance(node, ast.Let):
            visit(node.value, node.name if isinstance(node.value, ast.Lambda) else current, False)
            visit(node.body, current, tail)
        elif isinstance(node, ast.LetRec):
            for binding in node.bindings:
                visit(binding.value, binding.name, False)
            visit(node.body, current, tail)
        elif isinstance(node, ast.If):
            visit(node.condition, current, False)
            visit(node.consequent, current, tail)
            visit(node.alternative, current, tail)
        elif isinstance(node, ast.Match):
            visit(node.value, current, False)
            for case in node.cases:
                visit(case.body, current, tail)
        elif isinstance(node, ast.Sequence):
            for index, item in enumerate(node.items):
                visit(item, current, tail and index == len(node.items) - 1)
        elif isinstance(node, ast.Annotate):
            visit(node.value, current, tail)
        else:
            for child in ast.children(node):
                visit(child, current, False)

    visit(expression, caller, True)
    return tuple(result)


@dataclass(frozen=True)
class Warning:
    code: str
    message: str
    span: Span


def warnings(expression: ast.Expression) -> tuple[Warning, ...]:
    result = []
    for node in ast.walk(expression):
        if isinstance(node, ast.Lambda) and node.parameter not in free_names(node.body):
            if not node.parameter.startswith("_"):
                result.append(
                    Warning("unused-parameter", f"unused parameter {node.parameter}", node.span)
                )
        elif isinstance(node, ast.Let) and node.name not in free_names(node.body):
            if not node.name.startswith("_"):
                result.append(Warning("unused-binding", f"unused binding {node.name}", node.span))
        elif isinstance(node, ast.Sequence):
            for item in node.items[:-1]:
                if effects(item) == Effect.PURE:
                    result.append(
                        Warning("discarded-value", "pure expression value is discarded", item.span)
                    )
    return tuple(
        sorted(result, key=lambda item: (item.span.source, item.span.start.offset, item.code))
    )


def statistics(expression: ast.Expression) -> dict[str, int]:
    counts = {}
    depth = 0

    def visit(node, level):
        nonlocal depth
        name = type(node).__name__
        counts[name] = counts.get(name, 0) + 1
        depth = max(depth, level)
        for child in ast.children(node):
            visit(child, level + 1)

    visit(expression, 1)
    return {"nodes": sum(counts.values()), "depth": depth, **dict(sorted(counts.items()))}


def module_dependencies(module: ast.Module) -> dict[str, tuple[str, ...]]:
    definitions = {binding.name for binding in module.definitions}
    return {
        binding.name: tuple(sorted(free_names(binding.value) & definitions))
        for binding in sorted(module.definitions, key=lambda item: item.name)
    }
