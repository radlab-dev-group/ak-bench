"""A generation-checked read cache.

The cache holds records, and every entry carries the generation it was read
at. A lookup that cannot confirm the generation is still current returns a
miss: a cache that answers from a version the store has already replaced is
worse than no cache, because the answer is plausible and stale, and staleness
is the one failure a read path has no way to notice.

The rule that makes this a cache and not a second source of truth: **a write
invalidates, it does not update**. Writing through would let a caller read a
value the log has not yet made durable, and a crash between the two would
serve a value that never existed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .values import Record


@dataclass(frozen=True)
class Entry:
    record: Record
    generation: int
    hits: int = 0


@dataclass
class ReadCache:
    entries: dict[str, Entry] = field(default_factory=dict)
    lookups: int = 0
    hits: int = 0
    misses: int = 0
    invalidated: int = 0
    enabled: bool = True

    def get(self, key: str, *, current_generation: int) -> Record | None:
        """Return the cached record only while ``current_generation`` still matches."""

        self.lookups += 1
        if not self.enabled:
            self.misses += 1
            return None
        entry = self.entries.get(key)
        if entry is None or entry.generation != current_generation:
            self.misses += 1
            return None
        self.hits += 1
        self.entries[key] = Entry(record=entry.record, generation=entry.generation, hits=entry.hits + 1)
        return entry.record

    def put(self, record: Record) -> None:
        if not self.enabled:
            return
        self.entries[record.key] = Entry(record=record, generation=record.generation)

    def invalidate(self, key: str) -> None:
        self.invalidated += 1
        self.entries.pop(key, None)

    def clear(self) -> None:
        self.entries.clear()

    def stats(self) -> dict[str, int]:
        return {
            "entries": len(self.entries),
            "lookups": self.lookups,
            "hits": self.hits,
            "misses": self.misses,
            "invalidated": self.invalidated,
        }
