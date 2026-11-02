"""Structured compiler failures; callers never parse exception message prose."""

from dataclasses import dataclass

from .source import Source, Span


@dataclass(frozen=True)
class Related:
    message: str
    span: Span


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    span: Span
    related: tuple[Related, ...] = ()

    def document(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "span": self.span.document(),
            "related": [
                {"message": item.message, "span": item.span.document()} for item in self.related
            ],
        }

    def render(self, sources: dict[str, Source] | None = None) -> str:
        position = self.span.start
        heading = (
            f"{self.span.source}:{position.line}:{position.column}: {self.code}: {self.message}"
        )
        if sources and self.span.source in sources:
            source = sources[self.span.source]
            line = source.line(position.line)
            width = max(1, self.span.end.column - position.column)
            heading += "\n" + line + "\n" + " " * (position.column - 1) + "^" * min(width, 80)
        for item in self.related:
            heading += f"\n  {item.span.source}:{item.span.start.line}: {item.message}"
        return heading


class CompileError(ValueError):
    def __init__(self, code: str, message: str, span: Span, related: tuple[Related, ...] = ()):
        self.diagnostic = Diagnostic(code, message, span, related)
        self.code = code
        self.span = span
        super().__init__(self.diagnostic.render())


class EvaluationError(RuntimeError):
    def __init__(self, message: str, span: Span):
        self.span = span
        super().__init__(f"{span.source}:{span.start.line}: {message}")
