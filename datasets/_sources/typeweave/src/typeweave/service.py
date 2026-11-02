"""In-process editor service with versioned documents and structured diagnostics."""

from dataclasses import dataclass

from . import ast
from .analysis import statistics, warnings
from .buffer import Buffer, Edit
from .diagnostics import CompileError, Diagnostic
from .editor import Index, index, outline
from .parser import parse, parse_module
from .project import build, check_expression
from .types import render


@dataclass(frozen=True)
class Inspection:
    version: int
    digest: str
    type: str | None
    diagnostics: tuple[Diagnostic, ...]
    outline: tuple[dict, ...]
    statistics: dict

    def document(self) -> dict:
        return {
            "version": self.version,
            "digest": self.digest,
            "type": self.type,
            "diagnostics": [item.document() for item in self.diagnostics],
            "outline": list(self.outline),
            "statistics": self.statistics.copy(),
        }


class Service:
    def __init__(self) -> None:
        self.buffers: dict[str, Buffer] = {}
        self.syntax: dict[tuple[str, str, bool], ast.Node] = {}

    def open(self, name: str, text: str, version: int = 0) -> None:
        if name in self.buffers:
            raise ValueError("document is already open")
        self.buffers[name] = Buffer(name, text, version)

    def close(self, name: str) -> None:
        if name not in self.buffers:
            raise KeyError(name)
        del self.buffers[name]
        self.syntax = {key: value for key, value in self.syntax.items() if key[0] != name}

    def edit(self, name: str, edits: tuple[Edit, ...], version: int) -> None:
        self.buffers[name].apply(edits, version)
        self.syntax = {key: value for key, value in self.syntax.items() if key[0] != name}

    def parsed(self, name: str, *, module: bool = False) -> ast.Node:
        buffer = self.buffers[name]
        key = name, buffer.digest, module
        if key not in self.syntax:
            parser = parse_module if module else parse
            self.syntax[key] = parser(buffer.text, name)
        return self.syntax[key]

    def inspect(self, name: str, *, typing: bool = True) -> Inspection:
        buffer = self.buffers[name]
        try:
            syntax = self.parsed(name)
            inferred = render(check_expression(buffer.text, name=name)) if typing else None
            diagnostics = tuple(
                Diagnostic(item.code, item.message, item.span) for item in warnings(syntax)
            )
            information = index(syntax)
            symbols = tuple(
                {"name": symbol.name, "kind": symbol.kind, "span": symbol.definition.document()}
                for symbol in information.symbols
            )
            return Inspection(
                buffer.version, buffer.digest, inferred, diagnostics, symbols, statistics(syntax)
            )
        except CompileError as error:
            return Inspection(buffer.version, buffer.digest, None, (error.diagnostic,), (), {})

    def inspect_project(self) -> dict[str, tuple[Diagnostic, ...]]:
        sources = {name: buffer.text for name, buffer in self.buffers.items()}
        try:
            build(sources)
        except CompileError as error:
            return {error.span.source: (error.diagnostic,)}
        return dict.fromkeys(sorted(sources), ())

    def symbols(self, name: str) -> tuple[dict, ...]:
        syntax = self.parsed(name, module=True)
        return tuple(
            {"name": symbol.name, "kind": symbol.kind, "span": symbol.definition.document()}
            for symbol in outline(syntax)
        )

    def references(self, name: str) -> Index:
        return index(self.parsed(name))

    def checkpoint(self) -> dict:
        return {
            "version": 1,
            "documents": [self.buffers[name].document() for name in sorted(self.buffers)],
        }

    @classmethod
    def restore(cls, document: dict) -> "Service":
        if document.get("version") != 1 or not isinstance(document.get("documents"), list):
            raise ValueError("invalid editor checkpoint")
        service = cls()
        for row in document["documents"]:
            buffer = Buffer.load(row)
            if buffer.name in service.buffers:
                raise ValueError("duplicate editor document")
            service.buffers[buffer.name] = buffer
        return service
