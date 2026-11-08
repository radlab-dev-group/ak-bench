"""The audit trail: who wrote what, and under which epoch.

The audit log is not the WAL. The WAL is a recovery structure, and it is
correct to truncate it once a snapshot covers it; the audit trail is a
statement about authority, and it is appended to forever. They record
overlapping facts and are read for entirely different reasons, which is why
neither is derived from the other.

One line per admitted write: author, key, generation, epoch, replica count,
and whether the write was refused. A *refused* write is auditable too — "who
tried to commit against a stale generation" is the question an operator asks
after an incident, and a log that only records successes cannot answer it.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import asdict, dataclass, field
from typing import Iterator

AUDIT_FILE = "audit.jsonl"


@dataclass(frozen=True)
class AuditEntry:
    author: str
    key: str
    generation: int
    epoch: int
    replicas: int
    outcome: str
    detail: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class AuditLog:
    path: pathlib.Path | None = None
    entries: list[AuditEntry] = field(default_factory=list)
    enabled: bool = True

    def record(self, entry: AuditEntry) -> None:
        if not self.enabled:
            return
        self.entries.append(entry)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry.as_dict(), sort_keys=True) + "\n")

    def refusals(self) -> list[AuditEntry]:
        return [entry for entry in self.entries if entry.outcome != "ok"]

    def for_key(self, key: str) -> list[AuditEntry]:
        return [entry for entry in self.entries if entry.key == key]

    def tail(self, count: int = 20) -> Iterator[AuditEntry]:
        return iter(self.entries[-count:])

    def __len__(self) -> int:
        return len(self.entries)
