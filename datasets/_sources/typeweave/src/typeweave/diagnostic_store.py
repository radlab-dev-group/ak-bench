"""Revision-aware diagnostic collections and stable publication deltas."""

from dataclasses import dataclass

from .diagnostics import Diagnostic, Related
from .source import Position, Source, Span


def load_span(document: dict) -> Span:
    if not isinstance(document, dict) or set(document) != {"source", "start", "end"}:
        raise ValueError("invalid diagnostic span")
    positions = []
    for key in ("start", "end"):
        row = document[key]
        if set(row) != {"offset", "line", "column"} or any(
            type(value) is not int for value in row.values()
        ):
            raise ValueError("invalid diagnostic coordinate")
        if row["offset"] < 0 or row["line"] < 1 or row["column"] < 1:
            raise ValueError("negative diagnostic coordinate")
        positions.append(Position(**row))
    if positions[0].offset > positions[1].offset or not isinstance(document["source"], str):
        raise ValueError("invalid diagnostic extent")
    return Span(document["source"], *positions)


def load(document: dict) -> Diagnostic:
    if set(document) != {"code", "message", "span", "related"}:
        raise ValueError("invalid diagnostic fields")
    if (
        not isinstance(document["code"], str)
        or not document["code"]
        or not isinstance(document["message"], str)
    ):
        raise ValueError("invalid diagnostic code/message")
    related = tuple(Related(row["message"], load_span(row["span"])) for row in document["related"])
    return Diagnostic(document["code"], document["message"], load_span(document["span"]), related)


@dataclass(frozen=True)
class Publication:
    source: str
    version: int
    diagnostics: tuple[Diagnostic, ...]

    def document(self) -> dict:
        return {
            "source": self.source,
            "version": self.version,
            "diagnostics": [diagnostic.document() for diagnostic in self.diagnostics],
        }


class Diagnostics:
    def __init__(self) -> None:
        self.publications: dict[str, Publication] = {}

    def publish(
        self, source: Source, version: int, diagnostics: tuple[Diagnostic, ...]
    ) -> Publication:
        previous = self.publications.get(source.name)
        if (
            type(version) is not int
            or version < 0
            or (previous is not None and version <= previous.version)
        ):
            raise ValueError("stale diagnostic publication")
        for diagnostic in diagnostics:
            if diagnostic.span.source != source.name:
                raise ValueError("diagnostic belongs to another document")
            for position in (diagnostic.span.start, diagnostic.span.end):
                if source.position(position.offset) != position:
                    raise ValueError("diagnostic coordinates differ from source")
        unique = {
            (item.code, item.message, item.span.start.offset, item.span.end.offset): item
            for item in diagnostics
        }
        ordered = tuple(
            unique[key] for key in sorted(unique, key=lambda key: (key[2], key[3], key[0], key[1]))
        )
        publication = Publication(source.name, version, ordered)
        self.publications[source.name] = publication
        return publication

    def clear(self, source: Source, version: int) -> Publication:
        return self.publish(source, version, ())

    def document(self) -> dict:
        return {
            "version": 1,
            "publications": [
                publication.document() for name, publication in sorted(self.publications.items())
            ],
        }

    @classmethod
    def restore(cls, document: dict, sources: dict[str, Source]) -> "Diagnostics":
        if document.get("version") != 1 or not isinstance(document.get("publications"), list):
            raise ValueError("invalid diagnostic store")
        result = cls()
        for row in document["publications"]:
            source = row["source"]
            if source in result.publications or source not in sources:
                raise ValueError("unknown or duplicate diagnostic source")
            result.publish(
                sources[source], row["version"], tuple(load(item) for item in row["diagnostics"])
            )
        return result

    def delta(self, previous: "Diagnostics") -> tuple[Publication, ...]:
        return tuple(
            publication
            for name, publication in sorted(self.publications.items())
            if previous.publications.get(name) != publication
        )

    def render(self, sources: dict[str, Source]) -> str:
        return "\n".join(
            diagnostic.render(sources)
            for name, publication in sorted(self.publications.items())
            for diagnostic in publication.diagnostics
        )

    def counts(self) -> dict[str, int]:
        result = {}
        for publication in self.publications.values():
            for diagnostic in publication.diagnostics:
                result[diagnostic.code] = result.get(diagnostic.code, 0) + 1
        return dict(sorted(result.items()))
