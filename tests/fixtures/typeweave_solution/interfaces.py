"""Reference closed, canonical module interfaces and isolated importing."""

import json
from dataclasses import dataclass

from . import ast
from .diagnostics import CompileError
from .environment import ConstructorInfo, DataInfo, Environment
from .types import (
    Constructor,
    Scheme,
    Variable,
    decode_scheme,
    encode_scheme,
    free_variables,
    replace,
)


def canonical_scheme(scheme, solver):
    body = solver.apply(scheme.body)
    if free_variables(body) - set(scheme.quantified):
        raise ValueError("scheme contains weak variables")
    order = []

    def visit(term):
        if isinstance(term, Variable):
            if term.identity not in order:
                order.append(term.identity)
        else:
            for argument in term.arguments:
                visit(argument)

    visit(body)
    mapping = {identity: Variable(index) for index, identity in enumerate(order)}
    return encode_scheme(Scheme(tuple(range(len(order))), replace(body, mapping)))


@dataclass(frozen=True)
class Interface:
    module: str
    payload: str

    def document(self) -> dict:
        return json.loads(self.payload)

    @classmethod
    def load(cls, document: dict) -> "Interface":
        if not isinstance(document, dict) or set(document) != {
            "version",
            "module",
            "values",
            "data",
            "constructors",
            "dependencies",
        }:
            raise ValueError("invalid interface fields")
        if (
            document["version"] != 1
            or not isinstance(document["module"], str)
            or not document["module"]
        ):
            raise ValueError("invalid interface version or module")
        if any(
            not isinstance(document[key], dict)
            for key in ("values", "data", "constructors", "dependencies")
        ):
            raise ValueError("invalid interface tables")
        arities = {
            "Int": 0,
            "Bool": 0,
            "String": 0,
            "Unit": 0,
            "Ref": 1,
            "->": 2,
            "List": 1,
            "Option": 1,
        }
        known_data = {}
        for name, info in {**document["dependencies"], **document["data"]}.items():
            if (
                not isinstance(name, str)
                or not name
                or set(info) != {"name", "parameters", "constructors"}
            ):
                raise ValueError("invalid exported data")
            if not isinstance(info["name"], str) or "." not in info["name"]:
                raise ValueError("invalid nominal data identity")
            if name in document["data"] and not info["name"].startswith(document["module"] + "."):
                raise ValueError("public data owner is not the exporting module")
            parameters = info["parameters"]
            if parameters != list(range(len(parameters))):
                raise ValueError("noncanonical data parameters")
            if not isinstance(info["constructors"], list) or len(set(info["constructors"])) != len(
                info["constructors"]
            ):
                raise ValueError("invalid constructor family")
            arities[info["name"]] = len(parameters)
            known_data[info["name"]] = info

        def check(term):
            if isinstance(term, Variable):
                return
            if term.name != "Tuple" and (
                term.name not in arities or len(term.arguments) != arities[term.name]
            ):
                raise ValueError("interface contains an unknown or misapplied type")
            for argument in term.arguments:
                check(argument)

        for name, row in document["values"].items():
            if not isinstance(name, str) or not name or "." in name:
                raise ValueError("invalid export name")
            scheme = decode_scheme(row)
            if scheme.free:
                raise ValueError("interface value has free variables")
            check(scheme.body)
        for name, info in document["constructors"].items():
            if set(info) != {"name", "owner", "arity", "scheme"}:
                raise ValueError("invalid constructor metadata")
            if name not in document["values"] or info["scheme"] != document["values"][name]:
                raise ValueError("constructor is not an exported value")
            if (
                info["owner"] not in known_data
                or info["name"] not in known_data[info["owner"]]["constructors"]
            ):
                raise ValueError("constructor has unknown owner")
            if (
                info["name"] != document["module"] + "." + name
                or type(info["arity"]) is not int
                or info["arity"] < 0
            ):
                raise ValueError("invalid constructor name or arity")
            term = decode_scheme(info["scheme"]).body
            for _index in range(info["arity"]):
                if not isinstance(term, Constructor) or term.name != "->":
                    raise ValueError("constructor arrow arity mismatch")
                term = term.arguments[1]
            if not isinstance(term, Constructor) or term.name != info["owner"]:
                raise ValueError("constructor returns another data type")
        payload = json.dumps(document, sort_keys=True, separators=(",", ":"))
        return cls(document["module"], payload)


def export(module: ast.Module, environment: Environment, solver) -> Interface:
    if len(set(module.exports)) != len(module.exports):
        raise CompileError("duplicate-export", "duplicate export", module.span)
    local_values = {binding.name for binding in module.definitions}
    local_values.update(
        constructor.name for declaration in module.data for constructor in declaration.constructors
    )
    local_data = {declaration.name for declaration in module.data}
    document = {
        "version": 1,
        "module": module.name,
        "values": {},
        "data": {},
        "constructors": {},
        "dependencies": {},
    }
    for name in sorted(module.exports):
        if name in local_data:
            info = environment.data[name]
            document["data"][name] = {
                "name": info.name,
                "parameters": list(range(len(info.parameters))),
                "constructors": list(info.constructors),
            }
        if name in local_values:
            try:
                document["values"][name] = canonical_scheme(environment.values[name], solver)
            except ValueError as error:
                raise CompileError(
                    "weak-export", "cannot export a monomorphic weak type", module.span
                ) from error
        if name not in local_data and name not in local_values:
            raise CompileError("unknown-export", f"not a local export: {name}", module.span)
    for name in document["values"]:
        if name in environment.constructors:
            info = environment.constructors[name]
            document["constructors"][name] = {
                "name": info.name,
                "owner": info.owner,
                "arity": info.arity,
                "scheme": document["values"][name],
            }
    available = {info.name: info for info in environment.data.values()}
    public = {info["name"] for info in document["data"].values()}

    def collect(term):
        if isinstance(term, Variable):
            return
        if (
            term.name in available
            and term.name not in {"Option", "List"}
            and term.name not in public
        ):
            if term.name.startswith(module.name + "."):
                raise CompileError(
                    "private-type", "a public value mentions a private local type", module.span
                )
            info = available[term.name]
            document["dependencies"][info.name] = {
                "name": info.name,
                "parameters": list(range(len(info.parameters))),
                "constructors": list(info.constructors),
            }
        for argument in term.arguments:
            collect(argument)

    for row in document["values"].values():
        collect(decode_scheme(row).body)
    try:
        return Interface.load(document)
    except ValueError as error:
        raise CompileError(
            "private-type", "exported values mention a type that is not exported", module.span
        ) from error


def import_into(environment: Environment, interface: Interface, alias: str, solver) -> Environment:
    document = Interface.load(interface.document()).document()
    result = environment.extend({})
    imported_schemes = {}
    for name, row in document["values"].items():
        scheme = decode_scheme(row)
        mapping = {identity: solver.fresh() for identity in scheme.quantified}
        body = replace(scheme.body, mapping)
        freshened = Scheme(tuple(variable.identity for variable in mapping.values()), body)
        imported_schemes[name] = freshened
        result.values[alias + "." + name] = freshened
    for name, info in document["data"].items():
        parameters = tuple(solver.fresh().identity for parameter in info["parameters"])
        result.data[alias + "." + name] = DataInfo(
            info["name"], parameters, tuple(info["constructors"])
        )
    for _name, info in document["dependencies"].items():
        parameters = tuple(solver.fresh().identity for parameter in info["parameters"])
        result.data["__" + info["name"]] = DataInfo(
            info["name"], parameters, tuple(info["constructors"])
        )
    for name, info in document["constructors"].items():
        result.constructors[alias + "." + name] = ConstructorInfo(
            info["name"], info["owner"], imported_schemes[name], info["arity"]
        )
    return result
