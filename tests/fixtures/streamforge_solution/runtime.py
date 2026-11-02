"""Reference coordinator and defensive restoration; never copied to a seed."""

from dataclasses import asdict
from pathlib import Path

from . import checkpoint
from .clock import Watermarks
from .config import Pipeline
from .errors import IdentityConflict, InvalidCheckpoint, OffsetConflict
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

    def _flush(self) -> list[Change]:
        changes = self.changelog.reconcile(self.index.ready(self.watermark))
        self.changelog.forget(self.index.prune(self.watermark))
        return changes

    def ingest(self, event: Event) -> list[Change]:
        self.clock.require(event.partition)
        delivery = event.partition, event.offset
        if event.offset <= self.offsets[event.partition]:
            if self.deliveries.get(delivery) == event:
                return []
            raise OffsetConflict("consumed offset has a different delivery")
        if event.offset != self.offsets[event.partition] + 1:
            raise OffsetConflict("source offset gap")
        previous = self.identities.get(event.event_id)
        if previous is not None and previous != event.identity:
            raise IdentityConflict("event id has a different identity")
        self.offsets[event.partition] = event.offset
        self.deliveries[delivery] = event
        if previous is not None:
            return self._flush()
        self.identities[event.event_id] = event.identity
        if self.watermark is not None and event.timestamp + self.pipeline.lateness < self.watermark:
            self.late.append(LateEvent(event, self.watermark))
        else:
            self.index.add(event)
        return self._flush()

    def advance(self, partition: str, timestamp: int) -> list[Change]:
        self.clock.advance(partition, timestamp)
        return self._flush()

    def mark_idle(self, partition: str, idle: bool = True) -> list[Change]:
        self.clock.mark_idle(partition, idle)
        return self._flush()

    def checkpoint(self, path: Path) -> None:
        state = {
            "clock": self.clock.document(),
            "buckets": self.index.document(),
            "changelog": self.changelog.document(),
            "offsets": self.offsets.copy(),
            "deliveries": [asdict(self.deliveries[key]) for key in sorted(self.deliveries)],
            "identities": {key: list(value) for key, value in sorted(self.identities.items())},
            "late": [asdict(item) for item in self.late],
        }
        checkpoint.save(path, self.pipeline.fingerprint, state)

    @classmethod
    def restore(cls, pipeline: Pipeline, path: Path) -> "Processor":
        try:
            state = checkpoint.load(path, pipeline.fingerprint)
            processor = cls(pipeline)
            processor.clock = Watermarks.restore(pipeline.partitions, state["clock"])
            cls._validate_clock(processor.clock)
            if set(state["offsets"]) != set(pipeline.partitions):
                raise ValueError("offset partition mismatch")
            for name, offset in state["offsets"].items():
                if type(offset) is not int or offset < -1:
                    raise ValueError("invalid source offset")
                processor.offsets[name] = offset
            for row in state["deliveries"]:
                event = Event(**row)
                processor.clock.require(event.partition)
                address = event.partition, event.offset
                if address in processor.deliveries:
                    raise ValueError("duplicate source delivery")
                processor.deliveries[address] = event
                previous = processor.identities.setdefault(event.event_id, event.identity)
                if previous != event.identity:
                    raise ValueError("inconsistent event identity")
            for name, offset in processor.offsets.items():
                actual = sorted(
                    position for partition, position in processor.deliveries if partition == name
                )
                if len(actual) != offset + 1 or any(
                    position != expected for expected, position in enumerate(actual)
                ):
                    raise ValueError("source deliveries are not contiguous")
            expected_identities = {key: list(value) for key, value in processor.identities.items()}
            if state["identities"] != expected_identities:
                raise ValueError("identity table mismatch")
            late_ids = set()
            for row in state["late"]:
                event = Event(**row["event"])
                watermark = row["watermark"]
                if type(watermark) is not int or processor.watermark is None:
                    raise ValueError("invalid late watermark")
                if (
                    watermark > processor.watermark
                    or event.timestamp + pipeline.lateness >= watermark
                ):
                    raise ValueError("late record was not late")
                if processor.deliveries.get((event.partition, event.offset)) != event:
                    raise ValueError("late event was not consumed")
                if event.event_id in late_ids:
                    raise ValueError("duplicate late record")
                late_ids.add(event.event_id)
                processor.late.append(LateEvent(event, watermark))
            processor.index = WindowIndex.restore(pipeline, state["buckets"])
            rebuilt = WindowIndex(pipeline)
            accepted = set()
            for event in processor.deliveries.values():
                if event.event_id not in accepted and event.event_id not in late_ids:
                    rebuilt.add(event)
                    accepted.add(event.event_id)
            rebuilt.prune(processor.watermark)
            if rebuilt.document() != processor.index.document():
                raise ValueError("live index disagrees with accepted source history")
            processor.changelog = Changelog.restore(state["changelog"])
            visible = sorted(processor.changelog.visible.values())
            if visible != processor.index.ready(processor.watermark):
                raise ValueError("visible rows disagree with live closed buckets")
            return processor
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            if isinstance(error, InvalidCheckpoint):
                raise
            raise InvalidCheckpoint(str(error)) from error

    @staticmethod
    def _validate_clock(clock: Watermarks) -> None:
        reported = [value for value in clock.progress.values() if value is not None]
        if clock.value is not None and (not reported or clock.value > max(reported)):
            raise ValueError("global watermark exceeds every source watermark")
        active = [value for name, value in clock.progress.items() if name not in clock.idle]
        if (
            active
            and all(value is not None for value in active)
            and (clock.value is None or clock.value < min(active))
        ):
            raise ValueError("global watermark precedes active minimum")
