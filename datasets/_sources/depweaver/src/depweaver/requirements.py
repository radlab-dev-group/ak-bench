"""Human-readable requirement files with explicit marker and feature parsing."""

import re
from dataclasses import dataclass

from .model import Dependency, normalize

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True)
class LocatedRequirement:
    dependency: Dependency
    source: str
    line: int


def split_marker(text: str) -> tuple[str, str]:
    quote, escaped = None, False
    for index, character in enumerate(text):
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote is not None:
            escaped = True
        elif quote is not None:
            if character == quote:
                quote = None
        elif character in {"'", '"'}:
            quote = character
        elif character == ";":
            return text[:index].strip(), text[index + 1 :].strip()
    if quote is not None:
        raise ValueError("unclosed requirement string")
    return text.strip(), ""


def parse(text: str) -> Dependency:
    if not isinstance(text, str):
        raise ValueError("requirement must be a string")
    requirement, marker = split_marker(text.strip())
    match = NAME.match(requirement)
    if match is None:
        raise ValueError("requirement has no valid package name")
    name = match.group()
    rest = requirement[match.end() :].strip()
    extras = frozenset()
    if rest.startswith("["):
        close = rest.find("]")
        if close < 0:
            raise ValueError("unclosed extras list")
        values = rest[1:close].split(",")
        if any(not value.strip() for value in values):
            raise ValueError("empty requested extra")
        extras = frozenset(normalize(value.strip()) for value in values)
        rest = rest[close + 1 :].strip()
    if rest.startswith("("):
        if not rest.endswith(")"):
            raise ValueError("unclosed requirement version group")
        rest = rest[1:-1].strip()
    if "@" in rest or "://" in rest:
        raise ValueError("network/direct URL requirements are unsupported")
    return Dependency(name, rest or "*", extras, marker)


def format(dependency: Dependency) -> str:
    text = dependency.name
    if dependency.extras:
        text += "[" + ",".join(sorted(dependency.extras)) + "]"
    if str(dependency.spec) != "*":
        text += " " + str(dependency.spec)
    if dependency.marker.text:
        text += "; " + dependency.marker.text
    return text


def strip_comment(text: str) -> str:
    quote, escaped = None, False
    for index, character in enumerate(text):
        if escaped:
            escaped = False
        elif character == "\\" and quote:
            escaped = True
        elif quote:
            if character == quote:
                quote = None
        elif character in {"'", '"'}:
            quote = character
        elif character == "#" and (index == 0 or text[index - 1].isspace()):
            return text[:index].rstrip()
    return text.rstrip()


def read(text: str, source: str = "<requirements>") -> tuple[LocatedRequirement, ...]:
    result, fragments = [], []
    beginning = 1
    for number, raw in enumerate(text.splitlines(), 1):
        line = strip_comment(raw).strip()
        if not fragments:
            beginning = number
        if line.endswith("\\"):
            fragments.append(line[:-1].rstrip())
            continue
        fragments.append(line)
        requirement = " ".join(fragments).strip()
        fragments = []
        if not requirement:
            continue
        if requirement.startswith("-"):
            raise ValueError(f"{source}:{beginning}: directives are not allowed")
        try:
            dependency = parse(requirement)
        except ValueError as error:
            raise ValueError(f"{source}:{beginning}: {error}") from error
        result.append(LocatedRequirement(dependency, source, beginning))
    if fragments:
        raise ValueError(f"{source}:{beginning}: unfinished line continuation")
    return tuple(result)


def consolidate(dependencies: tuple[Dependency, ...]) -> tuple[Dependency, ...]:
    groups = {}
    for dependency in dependencies:
        key = dependency.name, dependency.marker.text
        if key not in groups:
            groups[key] = dependency
        else:
            previous = groups[key]
            groups[key] = Dependency(
                dependency.name,
                previous.spec & dependency.spec,
                previous.extras | dependency.extras,
                dependency.marker,
            )
    return tuple(groups[key] for key in sorted(groups))
