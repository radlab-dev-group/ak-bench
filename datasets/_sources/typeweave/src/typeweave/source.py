"""Immutable source coordinates shared by every compiler phase."""

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Position:
    offset: int
    line: int
    column: int


@dataclass(frozen=True)
class Span:
    source: str
    start: Position
    end: Position

    @classmethod
    def synthetic(cls, source: str = "<internal>") -> "Span":
        position = Position(0, 1, 1)
        return cls(source, position, position)

    def union(self, other: "Span") -> "Span":
        if self.source != other.source:
            raise ValueError("cannot combine spans from different sources")
        return Span(self.source, min(self.start, other.start), max(self.end, other.end))

    def document(self) -> dict:
        return {
            "source": self.source,
            "start": {
                "offset": self.start.offset,
                "line": self.start.line,
                "column": self.start.column,
            },
            "end": {"offset": self.end.offset, "line": self.end.line, "column": self.end.column},
        }


class Source:
    def __init__(self, text: str, name: str = "<input>") -> None:
        self.text = text
        self.name = name
        self.line_starts = [0]
        self.line_starts.extend(index + 1 for index, char in enumerate(text) if char == "\n")

    def position(self, offset: int) -> Position:
        from bisect import bisect_right

        if not 0 <= offset <= len(self.text):
            raise ValueError("offset outside source")
        line = bisect_right(self.line_starts, offset)
        return Position(offset, line, offset - self.line_starts[line - 1] + 1)

    def span(self, start: int, end: int) -> Span:
        if end < start:
            raise ValueError("inverted source span")
        return Span(self.name, self.position(start), self.position(end))

    def line(self, number: int) -> str:
        if not 1 <= number <= len(self.line_starts):
            raise ValueError("line outside source")
        start = self.line_starts[number - 1]
        end = self.line_starts[number] - 1 if number < len(self.line_starts) else len(self.text)
        return self.text[start:end]
