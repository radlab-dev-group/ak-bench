"""Lexer for the explicit S-expression surface language."""

import json
import re
from dataclasses import dataclass

from .diagnostics import CompileError
from .source import Source, Span

INTEGER = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
SYMBOL = re.compile(r"[A-Za-z_+*/<>=!?-][A-Za-z0-9_.'+*/<>=!?-]*\Z")


@dataclass(frozen=True)
class Token:
    kind: str
    value: str | int
    span: Span


def lex(source: Source | str, name: str = "<input>") -> tuple[Token, ...]:
    source = Source(source, name) if isinstance(source, str) else source
    tokens = []
    cursor = 0
    while cursor < len(source.text):
        character = source.text[cursor]
        if character.isspace():
            cursor += 1
            continue
        if character == ";":
            end = source.text.find("\n", cursor)
            cursor = len(source.text) if end < 0 else end
            continue
        start = cursor
        if character in "()":
            tokens.append(Token(character, character, source.span(cursor, cursor + 1)))
            cursor += 1
            continue
        if character == '"':
            cursor += 1
            escaped = False
            while cursor < len(source.text):
                current = source.text[cursor]
                cursor += 1
                if current == '"' and not escaped:
                    break
                escaped = bool(current == "\\" and not escaped)
            try:
                value = json.loads(source.text[start:cursor])
                if not isinstance(value, str):
                    raise ValueError("not a string")
            except ValueError as error:
                raise CompileError(
                    "lex", "invalid string literal", source.span(start, cursor)
                ) from error
            tokens.append(Token("string", value, source.span(start, cursor)))
            continue
        while (
            cursor < len(source.text)
            and not source.text[cursor].isspace()
            and source.text[cursor] not in "();"
        ):
            cursor += 1
        text = source.text[start:cursor]
        if INTEGER.fullmatch(text):
            tokens.append(Token("integer", int(text), source.span(start, cursor)))
        elif SYMBOL.fullmatch(text):
            tokens.append(Token("symbol", text, source.span(start, cursor)))
        else:
            raise CompileError("lex", f"invalid token {text!r}", source.span(start, cursor))
    tokens.append(Token("eof", "", source.span(len(source.text), len(source.text))))
    return tuple(tokens)
