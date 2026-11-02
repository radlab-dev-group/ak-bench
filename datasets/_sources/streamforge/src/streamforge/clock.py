"""Partition progress, explicit idleness, and a nondecreasing global watermark."""

from .model import integer


class Watermarks:
    def __init__(self, partitions: tuple[str, ...]) -> None:
        self.progress: dict[str, int | None] = dict.fromkeys(partitions)
        self.idle: set[str] = set()
        self.value: int | None = None

    def advance(self, partition: str, timestamp: int) -> int | None:
        self.require(partition)
        integer(timestamp, "watermark")
        previous = self.progress[partition]
        if previous is not None and timestamp < previous:
            raise ValueError("partition watermark cannot move backwards")
        self.progress[partition] = timestamp
        self._refresh()
        return self.value

    def mark_idle(self, partition: str, idle: bool = True) -> int | None:
        self.require(partition)
        if type(idle) is not bool:
            raise ValueError("idle must be a boolean")
        if idle:
            self.idle.add(partition)
        else:
            self.idle.discard(partition)
        self._refresh()
        return self.value

    def require(self, partition: str) -> None:
        if partition not in self.progress:
            raise ValueError("unknown partition")

    def _refresh(self) -> None:
        active = [value for name, value in self.progress.items() if name not in self.idle]
        if not active or any(value is None for value in active):
            return
        candidate = min(active)
        self.value = candidate if self.value is None else max(self.value, candidate)

    def document(self) -> dict:
        return {"progress": self.progress.copy(), "idle": sorted(self.idle), "value": self.value}

    @classmethod
    def restore(cls, partitions: tuple[str, ...], document: dict) -> "Watermarks":
        clock = cls(partitions)
        if set(document["progress"]) != set(partitions):
            raise ValueError("checkpoint partitions differ")
        for name, value in document["progress"].items():
            if value is not None:
                integer(value, "partition watermark")
            clock.progress[name] = value
        clock.idle = set(document["idle"])
        if not clock.idle <= set(partitions):
            raise ValueError("unknown idle partition")
        clock.value = document["value"]
        if clock.value is not None:
            integer(clock.value, "global watermark")
        return clock
