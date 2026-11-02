"""Implement the mutable window index described in README.md.

The index owns only unfinalized windows. Its document must preserve every
aggregate needed for restart, including session membership/bounds. A result
becomes eligible for output at watermark >= end; it is removed from this index
only at watermark > end + lateness. Session intervals that touch must merge
transitively, including windows that were already emitted but not finalized.
"""

from .config import Pipeline
from .model import Event, Result


class WindowIndex:
    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline
        self.buckets: dict = {}

    def add(self, event: Event) -> None:
        raise NotImplementedError("implement fixed, sliding and transitive session assignment")

    def ready(self, watermark: int | None) -> list[Result]:
        raise NotImplementedError("return closed, unfinalized results in canonical order")

    def prune(self, watermark: int | None) -> set[tuple[str, str, int, int]]:
        raise NotImplementedError("remove finalized buckets and return their addresses")

    def document(self) -> list[dict]:
        raise NotImplementedError("encode every live bucket as JSON-compatible state")

    @classmethod
    def restore(cls, pipeline: Pipeline, rows: list[dict]) -> "WindowIndex":
        raise NotImplementedError("rebuild the index from its checkpoint document")
