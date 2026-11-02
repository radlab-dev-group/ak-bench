"""Dependency-ordered module checking and execution from explicit source maps."""

from dataclasses import dataclass

from . import ast
from .declarations import register
from .diagnostics import CompileError
from .environment import Environment
from .inference import Inferencer
from .interfaces import Interface, export, import_into
from .interpreter import UNINITIALIZED, Interpreter, builtins, data_scope
from .names import components
from .parser import parse, parse_module
from .prelude import environment
from .types import Type


@dataclass(frozen=True)
class CheckedModule:
    syntax: ast.Module
    interface: Interface
    environment: Environment


@dataclass(frozen=True)
class Build:
    order: tuple[str, ...]
    modules: dict[str, CheckedModule]


def check_expression(text: str, *, name: str = "<input>", scope: Environment | None = None) -> Type:
    checker = Inferencer()
    term = checker.expression(parse(text, name), scope or environment())
    checker.finish()
    return checker.solver.apply(term)


def check_module(syntax: ast.Module, imports: dict[str, Interface] | None = None) -> CheckedModule:
    imports = imports or {}
    checker = Inferencer()
    scope = environment()
    aliases = set()
    for imported in syntax.imports:
        if imported.alias in aliases:
            raise CompileError("duplicate-import", "duplicate import alias", imported.span)
        aliases.add(imported.alias)
        if imported.module not in imports:
            raise CompileError(
                "missing-module", f"module not found: {imported.module}", imported.span
            )
        interface = imports[imported.module]
        if interface.module != imported.module:
            raise CompileError("invalid-interface", "module/interface name mismatch", imported.span)
        scope = import_into(scope, interface, imported.alias, checker.solver)
    scope = register(syntax, scope, checker.solver)
    scope = checker.group(syntax.definitions, scope)
    checker.finish()
    public = export(syntax, scope, checker.solver)
    return CheckedModule(syntax, public, scope)


def dependency_order(modules: dict[str, ast.Module]) -> tuple[str, ...]:
    visiting, visited, order = set(), set(), []

    def visit(name: str) -> None:
        if name in visited:
            return
        syntax = modules[name]
        if name in visiting:
            raise CompileError("module-cycle", f"cyclic module import: {name}", syntax.span)
        visiting.add(name)
        for imported in sorted(syntax.imports, key=lambda item: (item.module, item.alias)):
            if imported.module not in modules:
                raise CompileError(
                    "missing-module", f"module not found: {imported.module}", imported.span
                )
            visit(imported.module)
        visiting.remove(name)
        visited.add(name)
        order.append(name)

    for name in sorted(modules):
        visit(name)
    return tuple(order)


def build(sources: dict[str, str]) -> Build:
    syntax = {}
    for filename, text in sorted(sources.items()):
        module = parse_module(text, filename)
        if module.name in syntax:
            raise CompileError("duplicate-module", f"duplicate module {module.name}", module.span)
        syntax[module.name] = module
    order = dependency_order(syntax)
    checked = {}
    for name in order:
        checked[name] = check_module(
            syntax[name], {key: value.interface for key, value in checked.items()}
        )
    return Build(order, checked)


def execute(build_result: Build, module: str, binding: str, *, fuel: int = 100_000) -> object:
    scopes, tags = {}, {}
    remaining = fuel
    for name in build_result.order:
        checked = build_result.modules[name]
        scope = builtins()
        canonical = {}
        for imported in checked.syntax.imports:
            interface = build_result.modules[imported.module].interface.document()
            for exported in interface["values"]:
                scope.values[imported.alias + "." + exported] = scopes[imported.module].get(
                    exported, imported.span
                )
            for exported, original in tags[imported.module].items():
                if exported in interface["constructors"]:
                    canonical[imported.alias + "." + exported] = original
        canonical.update(data_scope(checked.syntax, scope))
        interpreter = Interpreter(fuel=remaining, constructors=canonical)
        for definition in checked.syntax.definitions:
            scope.values[definition.name] = UNINITIALIZED
        for group in components(checked.syntax.definitions):
            for definition in group:
                scope.values[definition.name] = interpreter.evaluate(definition.value, scope)
        remaining = interpreter.fuel
        scopes[name], tags[name] = scope, canonical
    if module not in scopes:
        raise KeyError(module)
    checked = build_result.modules[module]
    if binding not in checked.interface.document()["values"]:
        raise KeyError("binding is not exported")
    return scopes[module].get(binding, checked.syntax.span)
