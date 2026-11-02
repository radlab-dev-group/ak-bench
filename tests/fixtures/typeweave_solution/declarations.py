"""Reference nominal datatype and annotation elaboration."""

from . import ast
from .diagnostics import CompileError
from .environment import ConstructorInfo, DataInfo, Environment
from .types import Constructor, Scheme, Type, Variable, function


def annotation(
    syntax: ast.TypeSyntax, environment: Environment, solver, variables: dict | None = None
) -> Type:
    variables = {} if variables is None else variables
    name = syntax.name
    if name and name[0].islower() and "." not in name:
        if syntax.arguments:
            raise CompileError("type-arity", "a type variable cannot take arguments", syntax.span)
        if name not in variables:
            variables[name] = solver.fresh()
        return variables[name]
    builtins = {"Int": 0, "Bool": 0, "String": 0, "Unit": 0, "->": 2, "Ref": 1}
    if name in builtins:
        arity = builtins[name]
        canonical = name
    elif name == "Tuple":
        arity = len(syntax.arguments)
        canonical = name
    elif name in environment.data:
        info = environment.data[name]
        arity, canonical = len(info.parameters), info.name
    else:
        raise CompileError("unknown-type", f"unknown type {name}", syntax.span)
    if len(syntax.arguments) != arity:
        raise CompileError("type-arity", f"{name} expects {arity} type arguments", syntax.span)
    return Constructor(
        canonical,
        tuple(
            annotation(argument, environment, solver, variables) for argument in syntax.arguments
        ),
    )


def register(module: ast.Module, environment: Environment, solver) -> Environment:
    result = environment.extend({})
    seen = set()
    for declaration in module.data:
        if declaration.name in seen or declaration.name in result.data:
            raise CompileError("duplicate-type", "duplicate type declaration", declaration.span)
        seen.add(declaration.name)
        if len(set(declaration.parameters)) != len(declaration.parameters) or any(
            not name[0].islower() for name in declaration.parameters
        ):
            raise CompileError(
                "duplicate-parameter", "invalid or duplicate type parameter", declaration.span
            )
        parameters = tuple(solver.fresh().identity for name in declaration.parameters)
        canonical = module.name + "." + declaration.name
        constructors = tuple(module.name + "." + item.name for item in declaration.constructors)
        result.data[declaration.name] = DataInfo(canonical, parameters, constructors)
    for declaration in module.data:
        info = result.data[declaration.name]
        variables = dict(
            zip(
                declaration.parameters,
                (Variable(identity) for identity in info.parameters),
                strict=True,
            )
        )
        owner = Constructor(info.name, tuple(variables[name] for name in declaration.parameters))
        for constructor in declaration.constructors:
            if constructor.name in result.values or constructor.name in {
                binding.name for binding in module.definitions
            }:
                raise CompileError(
                    "duplicate-constructor", "constructor collides with a value", constructor.span
                )
            fields = []
            for syntax in constructor.fields:
                before = set(variables)
                term = annotation(syntax, result, solver, variables)
                if set(variables) != before:
                    raise CompileError(
                        "unbound-type-variable",
                        "constructor field uses an undeclared parameter",
                        syntax.span,
                    )
                fields.append(term)
            body = function(tuple(fields), owner)
            scheme = Scheme(info.parameters, body)
            canonical = module.name + "." + constructor.name
            result.values[constructor.name] = scheme
            result.constructors[constructor.name] = ConstructorInfo(
                canonical, info.name, scheme, len(fields)
            )
    return result
