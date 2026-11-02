"""Immutable type terms, schemes, substitutions and canonical type rendering."""

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Variable:
    identity: int


@dataclass(frozen=True)
class Constructor:
    name: str
    arguments: tuple["Type", ...] = ()


Type = Variable | Constructor
INT = Constructor("Int")
BOOL = Constructor("Bool")
STRING = Constructor("String")
UNIT = Constructor("Unit")


def arrow(argument: Type, result: Type) -> Constructor:
    return Constructor("->", (argument, result))


def function(arguments: tuple[Type, ...], result: Type) -> Type:
    for argument in reversed(arguments):
        result = arrow(argument, result)
    return result


def free_variables(term: Type) -> frozenset[int]:
    if isinstance(term, Variable):
        return frozenset({term.identity})
    return frozenset().union(*(free_variables(argument) for argument in term.arguments))


@dataclass(frozen=True)
class Scheme:
    quantified: tuple[int, ...]
    body: Type

    @property
    def free(self) -> frozenset[int]:
        return free_variables(self.body) - frozenset(self.quantified)


def replace(term: Type, substitutions: dict[int, Type]) -> Type:
    if isinstance(term, Variable):
        return substitutions.get(term.identity, term)
    return Constructor(
        term.name, tuple(replace(argument, substitutions) for argument in term.arguments)
    )


def render(term: Type) -> str:
    names = {}

    def name(identity: int) -> str:
        if identity not in names:
            index = len(names)
            names[identity] = "'" + chr(97 + index % 26) + (str(index // 26) if index >= 26 else "")
        return names[identity]

    def visit(current: Type, nested: bool = False) -> str:
        if isinstance(current, Variable):
            return name(current.identity)
        if current.name == "->":
            argument, result = current.arguments
            text = visit(argument, True) + " -> " + visit(result)
            return "(" + text + ")" if nested else text
        if current.name == "Tuple":
            return "(" + " * ".join(visit(argument, True) for argument in current.arguments) + ")"
        if not current.arguments:
            return current.name
        return (
            current.name + "[" + ", ".join(visit(argument) for argument in current.arguments) + "]"
        )

    return visit(term)


def encode(term: Type) -> dict:
    if isinstance(term, Variable):
        return {"variable": term.identity}
    return {
        "constructor": term.name,
        "arguments": [encode(argument) for argument in term.arguments],
    }


def decode(document: dict, *, depth: int = 0) -> Type:
    if depth > 200 or not isinstance(document, dict):
        raise ValueError("invalid or excessively nested type")
    if set(document) == {"variable"}:
        identity = document["variable"]
        if type(identity) is not int or identity < 0:
            raise ValueError("invalid type variable")
        return Variable(identity)
    if set(document) != {"constructor", "arguments"}:
        raise ValueError("invalid type object")
    name, arguments = document["constructor"], document["arguments"]
    if not isinstance(name, str) or not name or not isinstance(arguments, list):
        raise ValueError("invalid type constructor")
    if name in {"Int", "Bool", "String", "Unit"} and arguments:
        raise ValueError("primitive type applied to arguments")
    if (name == "->" and len(arguments) != 2) or (name == "Ref" and len(arguments) != 1):
        raise ValueError("invalid builtin type arity")
    return Constructor(name, tuple(decode(argument, depth=depth + 1) for argument in arguments))


def encode_scheme(scheme: Scheme) -> dict:
    return {"quantified": list(scheme.quantified), "body": encode(scheme.body)}


def decode_scheme(document: dict) -> Scheme:
    if set(document) != {"quantified", "body"} or not isinstance(document["quantified"], list):
        raise ValueError("invalid type scheme")
    quantified = tuple(document["quantified"])
    if any(type(identity) is not int or identity < 0 for identity in quantified):
        raise ValueError("invalid quantified variable")
    if len(set(quantified)) != len(quantified):
        raise ValueError("duplicate quantified variable")
    body = decode(document["body"])
    if not set(quantified) <= free_variables(body):
        raise ValueError("unused quantified variable")
    return Scheme(quantified, body)


def alpha_equivalent(first: Scheme, second: Scheme) -> bool:
    if len(first.quantified) != len(second.quantified):
        return False
    mapping = dict(
        zip(first.quantified, (Variable(identity) for identity in second.quantified), strict=True)
    )
    return replace(first.body, mapping) == second.body
