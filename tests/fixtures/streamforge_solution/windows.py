"""Reference operator implementation; never included in the agent seed."""

from dataclasses import asdict

from .aggregate import Accumulator
from .config import Pipeline
from .model import Event, Result


class WindowIndex:
    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline
        self.buckets: dict[tuple[str, str, int, int], Accumulator] = {}

    def add(self, event: Event) -> None:
        for window in self.pipeline.windows:
            if window.kind == "session":
                start, end = event.timestamp, event.timestamp + window.gap
                aggregate = Accumulator()
                aggregate.add(event.value)
                while True:
                    matches = [
                        address
                        for address in self.buckets
                        if address[:2] == (window.name, event.key)
                        and address[2] <= end
                        and address[3] >= start
                    ]
                    if not matches:
                        break
                    for address in sorted(matches):
                        aggregate.merge(self.buckets.pop(address))
                        start, end = min(start, address[2]), max(end, address[3])
                self.buckets[(window.name, event.key, start, end)] = aggregate
                continue
            step = window.size if window.kind == "fixed" else window.step
            start = event.timestamp // step * step
            while start + window.size > event.timestamp:
                address = (window.name, event.key, start, start + window.size)
                self.buckets.setdefault(address, Accumulator()).add(event.value)
                start -= step

    def ready(self, watermark: int | None) -> list[Result]:
        if watermark is None:
            return []
        return [
            aggregate.result(*address)
            for address, aggregate in sorted(self.buckets.items())
            if address[3] <= watermark
        ]

    def prune(self, watermark: int | None) -> set[tuple[str, str, int, int]]:
        if watermark is None:
            return set()
        expired = {
            address for address in self.buckets if watermark > address[3] + self.pipeline.lateness
        }
        for address in expired:
            del self.buckets[address]
        return expired

    def document(self) -> list[dict]:
        return [
            asdict(aggregate.result(*address))
            for address, aggregate in sorted(self.buckets.items())
        ]

    @classmethod
    def restore(cls, pipeline: Pipeline, rows: list[dict]) -> "WindowIndex":
        index = cls(pipeline)
        if not isinstance(rows, list):
            raise ValueError("buckets must be a list")
        windows = {window.name: window for window in pipeline.windows}
        for row in rows:
            result = Result(**row)
            if result.window not in windows or not isinstance(result.key, str) or not result.key:
                raise ValueError("unknown window or empty key")
            for value in (
                result.start,
                result.end,
                result.count,
                result.total,
                result.minimum,
                result.maximum,
            ):
                if type(value) is not int:
                    raise ValueError("bucket fields must be integers")
            if result.start >= result.end or result.count <= 0 or result.minimum > result.maximum:
                raise ValueError("invalid bucket bounds")
            if not result.minimum * result.count <= result.total <= result.maximum * result.count:
                raise ValueError("invalid aggregate")
            if result.count == 1 and not result.minimum == result.maximum == result.total:
                raise ValueError("single-event extrema disagree")
            window = windows[result.window]
            if window.kind != "session":
                step = window.size if window.kind == "fixed" else window.step
                if result.end - result.start != window.size or result.start % step:
                    raise ValueError("misaligned window")
            elif not window.gap <= result.end - result.start <= result.count * window.gap:
                raise ValueError("invalid session bounds")
            if result.address in index.buckets:
                raise ValueError("duplicate bucket address")
            index.buckets[result.address] = Accumulator(
                result.count, result.total, result.minimum, result.maximum
            )
        previous_sessions = {}
        for address in sorted(index.buckets):
            if windows[address[0]].kind == "session":
                group = address[:2]
                if group in previous_sessions and address[2] <= previous_sessions[group]:
                    raise ValueError("live sessions must not touch")
                previous_sessions[group] = address[3]
        return index
