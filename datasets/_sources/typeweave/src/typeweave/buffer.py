"""Versioned source buffers with UTF-16 positions and atomic editor edits."""

import hashlib
import itertools
from dataclasses import dataclass

from .source import Source


@dataclass(frozen=True, order=True)
class Coordinate:
    line: int
    character: int


@dataclass(frozen=True)
class Edit:
    start: Coordinate
    end: Coordinate
    text: str


class Buffer:
    def __init__(self, name: str, text: str = "", version: int = 0) -> None:
        if type(version) is not int or version < 0:
            raise ValueError("invalid document version")
        self.name, self.text, self.version = name, text, version

    @property
    def source(self) -> Source:
        return Source(self.text, self.name)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()

    def offset(self, coordinate: Coordinate) -> int:
        source = self.source
        if (
            type(coordinate.line) is not int
            or type(coordinate.character) is not int
            or coordinate.line < 0
            or coordinate.character < 0
        ):
            raise ValueError("invalid editor coordinate")
        if coordinate.line >= len(source.line_starts):
            raise ValueError("editor line outside document")
        text = source.line(coordinate.line + 1)
        units = 0
        for index, character in enumerate(text):
            if units == coordinate.character:
                return source.line_starts[coordinate.line] + index
            units += 2 if ord(character) > 0xFFFF else 1
            if units > coordinate.character:
                raise ValueError("coordinate splits a UTF-16 surrogate pair")
        if units != coordinate.character:
            raise ValueError("editor column outside line")
        return source.line_starts[coordinate.line] + len(text)

    def coordinate(self, offset: int) -> Coordinate:
        position = self.source.position(offset)
        start = self.source.line_starts[position.line - 1]
        units = sum(2 if ord(character) > 0xFFFF else 1 for character in self.text[start:offset])
        return Coordinate(position.line - 1, units)

    def apply(self, edits: tuple[Edit, ...], version: int) -> None:
        if type(version) is not int or version <= self.version:
            raise ValueError("stale document version")
        intervals = []
        for edit in edits:
            start, end = self.offset(edit.start), self.offset(edit.end)
            if start > end or not isinstance(edit.text, str):
                raise ValueError("invalid editor edit")
            intervals.append((start, end, edit.text))
        intervals.sort(key=lambda row: (row[0], row[1]))
        if any(
            first[1] > second[0] or first[0] == second[0]
            for first, second in itertools.pairwise(intervals)
        ):
            raise ValueError("overlapping editor edits")
        text = self.text
        for start, end, replacement in reversed(intervals):
            text = text[:start] + replacement + text[end:]
        self.text, self.version = text, version

    def replace(self, text: str, version: int) -> None:
        if type(version) is not int or version <= self.version or not isinstance(text, str):
            raise ValueError("invalid document replacement")
        self.text, self.version = text, version

    def document(self) -> dict:
        return {
            "name": self.name,
            "text": self.text,
            "version": self.version,
            "sha256": self.digest,
        }

    @classmethod
    def load(cls, document: dict) -> "Buffer":
        if set(document) != {"name", "text", "version", "sha256"}:
            raise ValueError("invalid buffer document")
        buffer = cls(document["name"], document["text"], document["version"])
        if buffer.digest != document["sha256"]:
            raise ValueError("buffer checksum mismatch")
        return buffer
