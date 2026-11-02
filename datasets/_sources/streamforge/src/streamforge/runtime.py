"""Implement the coordinator according to README.md; preserve the public API.

The clock, envelope codec, records and aggregate primitives already work.
ingest, advance, mark_idle, checkpoint and restore must coordinate the index,
deduplication, source offsets, late side output, and changelog atomically.
"""

from pathlib import Path

from .clock import Watermarks
from .config import Pipeline
from .model import Change, Event, LateEvent
from .reconcile import Changelog
from .windows import WindowIndex


class Processor:
    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline
        self.clock = Watermarks(pipeline.partitions)
        self.index = WindowIndex(pipeline)
        self.changelog = Changelog()
        self.offsets: dict[str, int] = dict.fromkeys(pipeline.partitions, -1)
        self.deliveries: dict[tuple[str, int], Event] = {}
        self.identities: dict[str, tuple[str, int, int]] = {}
        self.late: list[LateEvent] = []

    @property
    def watermark(self) -> int | None:
        return self.clock.value

    def ingest(self, event: Event) -> list[Change]:
        raise NotImplementedError("validate, deduplicate, consume, assign and reconcile")

    def advance(self, partition: str, timestamp: int) -> list[Change]:
        raise NotImplementedError("advance partition progress, reconcile, then finalize")

    def mark_idle(self, partition: str, idle: bool = True) -> list[Change]:
        raise NotImplementedError("change idleness, reconcile, then finalize")

    def checkpoint(self, path: Path) -> None:
        raise NotImplementedError("persist complete independent restart state")

    @classmethod
    def restore(cls, pipeline: Pipeline, path: Path) -> "Processor":
        raise NotImplementedError("restore or raise InvalidCheckpoint; never emit during restore")
