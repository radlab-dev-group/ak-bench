"""The append-only event trace and its digest.

A simulation explains itself through its trace. Every decision a node makes,
every message the network delivers or drops, every action a schedule
applies, is one :class:`TraceEvent` with a tick, an origin, a kind and a
flat dictionary of fields. The trace is append-only: nothing in the package
edits or removes an event after it was recorded, and the sequence number is
the position in the file.

Two renderings exist. ``render_text`` is for humans and is deliberately one
line per event so that ``grep`` works. ``to_jsonl`` is for tools and is
canonical: keys sorted, no whitespace, one object per line. Both are pure
functions of the events, so two traces that render the same are the same.

The **digest** (:meth:`Trace.digest`) is a SHA-256 over the canonical JSON
of the events whose kind is in :data:`DIGEST_KINDS` — the *committed-visible*
events: ``commit``, ``apply``, ``snapshot`` and ``violation``. Message-level
events are
excluded on purpose (``docs/adr/ADR-0010``): a change to heartbeat batching
or network delay bookkeeping must not invalidate every reference digest in
``traces/`` unless it also changed what got committed, where, and when.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator

from .errors import TraceError

#: Event kinds that take part in the digest. Closed; see ADR-0010.
DIGEST_KINDS: tuple[str, ...] = ("commit", "apply", "snapshot", "violation")

#: Every kind the seed records, grouped by origin. Documentation, not a
#: validation gate: a trace reader must not fail on a kind it does not know,
#: because the declared features will add kinds.
NODE_KINDS = (
    "start", "timeout", "prevote_start", "election_start", "vote", "prevote",
    "leader", "step_down", "append", "truncate", "reject_append", "commit",
    "apply", "propose", "crash", "restart", "skew", "snapshot", "snapshot_installed",
)
NETWORK_KINDS = ("send", "deliver", "drop", "dup", "partition", "heal", "block", "unblock", "network")
CLUSTER_KINDS = ("schedule", "propose_pending", "propose_rejected", "violation", "end")


@dataclass(frozen=True)
class TraceEvent:
    seq: int
    tick: int
    node: str
    kind: str
    fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "tick": self.tick,
            "node": self.node,
            "kind": self.kind,
            "fields": {k: self.fields[k] for k in sorted(self.fields)},
        }

    def canonical(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def render(self) -> str:
        parts = " ".join(f"{k}={_render_value(self.fields[k])}" for k in sorted(self.fields))
        origin = self.node or "-"
        return f"{self.seq:07d} t={self.tick:06d} {origin:<6} {self.kind:<16} {parts}".rstrip()

    def digest_material(self) -> str:
        body = {"tick": self.tick, "node": self.node, "kind": self.kind,
                "fields": {k: self.fields[k] for k in sorted(self.fields)}}
        return json.dumps(body, sort_keys=True, separators=(",", ":"))


def _render_value(value: Any) -> str:
    if isinstance(value, str):
        return value if value and " " not in value else repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_render_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(f"{k}:{_render_value(v)}" for k, v in sorted(value.items())) + "}"
    return str(value)


class Trace:
    """The event list, plus the digest and the renderers."""

    def __init__(self) -> None:
        self._events: list[TraceEvent] = []
        self._listeners: list[Callable[[TraceEvent], None]] = []

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[TraceEvent]:
        return iter(self._events)

    def __getitem__(self, index: int) -> TraceEvent:
        return self._events[index]

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        return tuple(self._events)

    def subscribe(self, listener: Callable[[TraceEvent], None]) -> None:
        """Call ``listener`` with every event as it is recorded. Used by the
        CLI to stream text output while a long schedule runs."""

        self._listeners.append(listener)

    def record(self, tick: int, node: str, kind: str, **fields: Any) -> TraceEvent:
        event = TraceEvent(seq=len(self._events), tick=tick, node=node, kind=kind, fields=dict(fields))
        self._events.append(event)
        for listener in self._listeners:
            listener(event)
        return event

    # -- queries ---------------------------------------------------------

    def of_kind(self, *kinds: str) -> list[TraceEvent]:
        wanted = set(kinds)
        return [e for e in self._events if e.kind in wanted]

    def for_node(self, node: str) -> list[TraceEvent]:
        return [e for e in self._events if e.node == node]

    def between(self, start: int, end: int) -> list[TraceEvent]:
        return [e for e in self._events if start <= e.tick <= end]

    def last(self, kind: str | None = None) -> TraceEvent | None:
        for event in reversed(self._events):
            if kind is None or event.kind == kind:
                return event
        return None

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for event in self._events:
            out[event.kind] = out.get(event.kind, 0) + 1
        return dict(sorted(out.items()))

    # -- digest ----------------------------------------------------------

    def digest_events(self) -> list[TraceEvent]:
        return [e for e in self._events if e.kind in DIGEST_KINDS]

    def digest(self) -> str:
        return digest_of(self.digest_events())

    # -- rendering -------------------------------------------------------

    def render_text(self, events: Iterable[TraceEvent] | None = None) -> str:
        return "\n".join(e.render() for e in (self._events if events is None else events))

    def to_jsonl(self) -> str:
        return "\n".join(e.canonical() for e in self._events) + ("\n" if self._events else "")

    def write_jsonl(self, path: str | pathlib.Path) -> int:
        path = pathlib.Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_jsonl(), encoding="utf-8")
        return len(self._events)

    @classmethod
    def read_jsonl(cls, path: str | pathlib.Path) -> "Trace":
        trace = cls()
        path = pathlib.Path(path)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise TraceError(f"cannot read trace {path}: {exc}") from exc
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TraceError(f"{path}:{number}: not JSON: {exc}") from exc
            try:
                event = TraceEvent(
                    seq=int(data["seq"]), tick=int(data["tick"]), node=str(data["node"]),
                    kind=str(data["kind"]), fields=dict(data.get("fields", {})),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise TraceError(f"{path}:{number}: malformed event: {exc}") from exc
            if event.seq != len(trace._events):
                raise TraceError(f"{path}:{number}: sequence gap, expected {len(trace._events)} got {event.seq}")
            trace._events.append(event)
        return trace


def digest_of(events: Iterable[TraceEvent]) -> str:
    h = hashlib.sha256()
    for event in events:
        h.update(event.digest_material().encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


@dataclass(frozen=True)
class Divergence:
    """Where two traces part ways. ``position`` indexes the digest-event
    list, not the raw event list, when ``digest_only`` was requested."""

    position: int
    left: TraceEvent | None
    right: TraceEvent | None

    def render(self) -> str:
        l = self.left.render() if self.left else "<end of trace>"
        r = self.right.render() if self.right else "<end of trace>"
        return f"first divergence at position {self.position}:\n  reference: {l}\n  actual:    {r}"


def first_divergence(reference: Trace, actual: Trace, digest_only: bool = True) -> Divergence | None:
    """The first event at which ``actual`` differs from ``reference``, or
    ``None`` when they agree. Comparison ignores ``seq`` when restricted to
    digest events, because the surrounding message events may legitimately
    have shifted."""

    left = reference.digest_events() if digest_only else list(reference)
    right = actual.digest_events() if digest_only else list(actual)
    for position in range(max(len(left), len(right))):
        a = left[position] if position < len(left) else None
        b = right[position] if position < len(right) else None
        if a is None or b is None:
            return Divergence(position, a, b)
        if a.digest_material() != b.digest_material():
            return Divergence(position, a, b)
    return None
