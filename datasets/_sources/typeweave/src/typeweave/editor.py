"""Read-only symbol/navigation services over parsed syntax, without inference."""

from dataclasses import dataclass

from . import ast
from .source import Span


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    definition: Span
    scope: Span


@dataclass(frozen=True)
class Reference:
    name: str
    span: Span
    definition: Span | None


@dataclass(frozen=True)
class Index:
    symbols: tuple[Symbol, ...]
    references: tuple[Reference, ...]

    def at(self, offset: int) -> Symbol | Reference | None:
        references = [
            item
            for item in self.references
            if item.span.start.offset <= offset < item.span.end.offset
        ]
        if references:
            return min(references, key=lambda item: item.span.end.offset - item.span.start.offset)
        symbols = [
            item
            for item in self.symbols
            if item.definition.start.offset <= offset < item.definition.end.offset
        ]
        return (
            min(symbols, key=lambda item: item.definition.end.offset - item.definition.start.offset)
            if symbols
            else None
        )

    def usages(self, definition: Span) -> tuple[Reference, ...]:
        return tuple(item for item in self.references if item.definition == definition)

    def completions(self, offset: int, prefix: str = "") -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    item.name
                    for item in self.symbols
                    if item.name.startswith(prefix)
                    and item.scope.start.offset <= offset <= item.scope.end.offset
                }
            )
        )


def index(expression: ast.Expression, initial: dict[str, Span] | None = None) -> Index:
    symbols, references = [], []

    def bind(name: str, definition: Span, scope: Span, environment: dict) -> dict:
        symbols.append(Symbol(name, "value", definition, scope))
        return {**environment, name: definition}

    def visit(node: ast.Expression, environment: dict) -> None:
        if isinstance(node, ast.Variable):
            references.append(Reference(node.name, node.span, environment.get(node.name)))
        elif isinstance(node, ast.Lambda):
            visit(node.body, bind(node.parameter, node.span, node.body.span, environment))
        elif isinstance(node, ast.Let):
            visit(node.value, environment)
            visit(node.body, bind(node.name, node.span, node.body.span, environment))
        elif isinstance(node, ast.LetRec):
            extended = environment.copy()
            for binding in node.bindings:
                extended = bind(binding.name, binding.span, node.span, extended)
            for binding in node.bindings:
                visit(binding.value, extended)
            visit(node.body, extended)
        elif isinstance(node, ast.Match):
            visit(node.value, environment)
            for case in node.cases:
                extended = environment.copy()
                for name in ast.pattern_names(case.pattern):
                    extended = bind(name, case.pattern.span, case.body.span, extended)
                visit(case.body, extended)
        else:
            for child in ast.children(node):
                visit(child, environment)

    visit(expression, initial or {})
    return Index(tuple(symbols), tuple(references))


def outline(module: ast.Module) -> tuple[Symbol, ...]:
    symbols = []
    for imported in module.imports:
        symbols.append(Symbol(imported.alias, "module", imported.span, module.span))
    for declaration in module.data:
        symbols.append(Symbol(declaration.name, "type", declaration.span, module.span))
        for constructor in declaration.constructors:
            symbols.append(Symbol(constructor.name, "constructor", constructor.span, module.span))
    for definition in module.definitions:
        symbols.append(Symbol(definition.name, "value", definition.span, module.span))
    return tuple(symbols)


def rename_edits(
    expression: ast.Expression, definition: Span, replacement: str
) -> tuple[tuple[Span, str], ...]:
    from .parser import forms, identifier

    parsed = forms(replacement)
    if len(parsed) != 1:
        raise ValueError("replacement is not a binding name")
    identifier(parsed[0])
    information = index(expression)
    symbols = [symbol for symbol in information.symbols if symbol.definition == definition]
    if len(symbols) != 1:
        raise ValueError("ambiguous or missing binding")
    symbol = symbols[0]
    if replacement != symbol.name and any(
        item.name == replacement and item.scope == symbol.scope for item in information.symbols
    ):
        raise ValueError("rename would collide with another binding")
    return tuple((item.span, replacement) for item in information.usages(definition))
