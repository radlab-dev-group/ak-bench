"""Explicit marker grammar; never evaluate input as Python code."""

import hashlib
import json
import re
from dataclasses import dataclass

from .versions import Version

FIELDS = {"python_version", "sys_platform", "platform_machine", "implementation_name", "extra"}
TOKEN = re.compile(
    r"""\s*(?:(?P<string>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(?P<operator>==|!=|>=|<=|>|<)|(?P<word>[A-Za-z_][A-Za-z_0-9]*)|(?P<parenthesis>[()]))"""
)


@dataclass(frozen=True)
class Target:
    python_version: str = "3.12.0"
    sys_platform: str = "linux"
    platform_machine: str = "x86_64"
    implementation_name: str = "cpython"

    def __post_init__(self) -> None:
        Version.coerce(self.python_version)
        if not all(isinstance(value, str) and value for value in self.document().values()):
            raise ValueError("target fields must be nonempty strings")

    def document(self) -> dict:
        return {
            "python_version": self.python_version,
            "sys_platform": self.sys_platform,
            "platform_machine": self.platform_machine,
            "implementation_name": self.implementation_name,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.document(), sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Expression:
    operation: str
    arguments: tuple

    def evaluate(self, target: Target, extra: str) -> bool:
        if self.operation == "true":
            return True
        if self.operation == "and":
            return all(argument.evaluate(target, extra) for argument in self.arguments)
        if self.operation == "or":
            return any(argument.evaluate(target, extra) for argument in self.arguments)
        field, operation, literal = self.arguments
        value = extra if field == "extra" else getattr(target, field)
        if operation in {"in", "not in"}:
            found = value in literal.split(",")
            return not found if operation == "not in" else found
        if field == "python_version":
            first, second = Version.coerce(value), Version.coerce(literal)
        else:
            first, second = value, literal
        return {
            "==": first == second,
            "!=": first != second,
            ">=": first >= second,
            "<=": first <= second,
            ">": first > second,
            "<": first < second,
        }[operation]


class Parser:
    def __init__(self, text: str) -> None:
        self.tokens = []
        cursor = 0
        while cursor < len(text):
            if not text[cursor:].strip():
                break
            match = TOKEN.match(text, cursor)
            if not match:
                raise ValueError(f"invalid marker near {text[cursor:]!r}")
            self.tokens.append((match.lastgroup, match.group(match.lastgroup)))
            cursor = match.end()
        self.cursor = 0

    def peek(self, text: str) -> bool:
        return self.cursor < len(self.tokens) and self.tokens[self.cursor][1] == text

    def take(self) -> tuple[str, str]:
        if self.cursor == len(self.tokens):
            raise ValueError("unexpected end of marker")
        token = self.tokens[self.cursor]
        self.cursor += 1
        return token

    def disjunction(self) -> Expression:
        terms = [self.conjunction()]
        while self.peek("or"):
            self.take()
            terms.append(self.conjunction())
        return terms[0] if len(terms) == 1 else Expression("or", tuple(terms))

    def conjunction(self) -> Expression:
        terms = [self.atom()]
        while self.peek("and"):
            self.take()
            terms.append(self.atom())
        return terms[0] if len(terms) == 1 else Expression("and", tuple(terms))

    def atom(self) -> Expression:
        if self.peek("("):
            self.take()
            result = self.disjunction()
            if not self.peek(")"):
                raise ValueError("unclosed marker group")
            self.take()
            return result
        kind, field = self.take()
        if kind != "word" or field not in FIELDS:
            raise ValueError("unknown marker field")
        kind, operation = self.take()
        if operation == "not":
            if self.take()[1] != "in":
                raise ValueError("expected 'not in'")
            operation = "not in"
        if kind != "operator" and operation not in {"in", "not in"}:
            raise ValueError("invalid marker comparison")
        kind, literal = self.take()
        if kind != "string":
            raise ValueError("marker comparison requires a quoted string")
        if literal[0] == "'":
            literal = '"' + literal[1:-1].replace('"', '\\"') + '"'
        value = json.loads(literal)
        if field == "python_version" and operation not in {"in", "not in"}:
            Version.coerce(value)
        return Expression("compare", (field, operation, value))


@dataclass(frozen=True)
class Marker:
    text: str = ""

    def __post_init__(self) -> None:
        self.expression()

    def expression(self) -> Expression:
        if not self.text.strip():
            return Expression("true", ())
        parser = Parser(self.text)
        expression = parser.disjunction()
        if parser.cursor != len(parser.tokens):
            raise ValueError("trailing marker tokens")
        return expression

    def matches(self, target: Target, extras: frozenset[str] = frozenset()) -> bool:
        expression = self.expression()
        return any(expression.evaluate(target, extra) for extra in sorted(extras) or [""])
