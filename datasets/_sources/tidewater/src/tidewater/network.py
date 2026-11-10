"""Deterministic message delivery with faults.

The network is a queue of :class:`~tidewater.messages.Envelope` keyed by
delivery tick. Every decision it makes — how long a message takes, whether
it is dropped, whether it is duplicated — comes from one seeded stream,
``rng.stream("network")``, and from the fault state a schedule has set:
partitions, blocked links, downed nodes, and the rate options.

Rules (``SPEC.md`` section 1.4):

* **delay** — every message gets ``randint(min_delay, max_delay)`` ticks;
  two messages sent in the same tick to the same destination can therefore
  arrive in either order, which is how reordering happens. There is no
  separate "reorder" knob;
* **drop** — a message to an unreachable destination (other side of a
  partition, blocked link, crashed node) is dropped at *send* time and
  traced with the reason. A random drop (``drop_rate``) is also decided at
  send time, so the decision does not depend on what else is in flight;
* **in-flight messages survive a partition** — a message already queued
  when a partition is declared is still delivered, because that is what
  real networks do and because the alternative (scanning the queue on
  every fault) makes the delivery order depend on schedule timing in ways
  that are hard to reason about. A message to a node that crashes before
  delivery *is* dropped at delivery time: a dead process cannot receive;
* **duplicate** — with ``dup_rate`` a second envelope is queued with its own
  delay; it carries ``duplicate_of`` for the trace.

The order in which same-tick deliveries are handed to nodes is
``(deliver_at, seq)``: sends are sequenced in the order the cluster drained
node outboxes, which is node-id order, so the whole thing is a pure function
of the seed and the schedule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .clock import EventQueue
from .errors import ConfigurationError
from .messages import Envelope, Message
from .rng import Stream
from .trace import Trace


@dataclass(frozen=True)
class NetworkOptions:
    min_delay: int = 1
    max_delay: int = 3
    drop_rate: float = 0.0
    dup_rate: float = 0.0
    dup_extra_delay: int = 4

    def __post_init__(self) -> None:
        if self.min_delay < 1:
            raise ConfigurationError("min_delay must be at least 1: a message never arrives in the tick it was sent")
        if self.max_delay < self.min_delay:
            raise ConfigurationError("max_delay must be >= min_delay")
        if not 0.0 <= self.drop_rate < 1.0:
            raise ConfigurationError("drop_rate must be in [0, 1)")
        if not 0.0 <= self.dup_rate < 1.0:
            raise ConfigurationError("dup_rate must be in [0, 1)")
        if self.dup_extra_delay < 0:
            raise ConfigurationError("dup_extra_delay cannot be negative")

    def replace(self, **changes: Any) -> "NetworkOptions":
        values = self.to_dict()
        values.update(changes)
        return NetworkOptions(**values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_delay": self.min_delay,
            "max_delay": self.max_delay,
            "drop_rate": self.drop_rate,
            "dup_rate": self.dup_rate,
            "dup_extra_delay": self.dup_extra_delay,
        }


class Network:
    """The message fabric between nodes."""

    def __init__(self, rng: Stream, trace: Trace, options: NetworkOptions | None = None) -> None:
        self.rng = rng
        self.trace = trace
        self.options = options or NetworkOptions()
        self.queue = EventQueue()
        self.now = 0
        self._seq = 0
        self.groups: list[frozenset[str]] | None = None
        self.blocked: set[tuple[str, str]] = set()
        self.down: set[str] = set()
        self.sent = 0
        self.delivered = 0
        self.dropped = 0
        self.duplicated = 0

    # -- fault state -------------------------------------------------------

    def partition(self, groups: Iterable[Iterable[str]]) -> None:
        """Split the cluster into the given groups. A node in no group is
        alone. Replaces any earlier partition."""

        sets = [frozenset(g) for g in groups]
        seen: set[str] = set()
        for group in sets:
            if group & seen:
                raise ConfigurationError("partition groups must be disjoint")
            seen |= group
        self.groups = sets
        self.trace.record(self.now, "", "partition", groups=[sorted(g) for g in sets])

    def heal(self) -> None:
        self.groups = None
        self.blocked.clear()
        self.trace.record(self.now, "", "heal")

    def isolate(self, node_id: str, others: Iterable[str]) -> None:
        self.partition([[node_id], [o for o in others if o != node_id]])

    def block(self, src: str, dst: str, both_ways: bool = True) -> None:
        self.blocked.add((src, dst))
        if both_ways:
            self.blocked.add((dst, src))
        self.trace.record(self.now, "", "block", src=src, dst=dst, both=both_ways)

    def unblock(self, src: str, dst: str, both_ways: bool = True) -> None:
        self.blocked.discard((src, dst))
        if both_ways:
            self.blocked.discard((dst, src))
        self.trace.record(self.now, "", "unblock", src=src, dst=dst, both=both_ways)

    def mark_down(self, node_id: str) -> None:
        self.down.add(node_id)

    def mark_up(self, node_id: str) -> None:
        self.down.discard(node_id)

    def set_options(self, **changes: Any) -> NetworkOptions:
        self.options = self.options.replace(**changes)
        self.trace.record(self.now, "", "network", **self.options.to_dict())
        return self.options

    def reachable(self, src: str, dst: str) -> str | None:
        """``None`` if a message can pass, else the reason it cannot."""

        if dst in self.down:
            return "dst_down"
        if src in self.down:
            return "src_down"
        if (src, dst) in self.blocked:
            return "blocked"
        if self.groups is not None:
            group_of = {n: i for i, g in enumerate(self.groups) for n in g}
            if group_of.get(src, -1) != group_of.get(dst, -2):
                return "partition"
        return None

    # -- traffic -----------------------------------------------------------

    def send(self, src: str, dst: str, message: Message) -> Envelope | None:
        """Queue ``message``; return the envelope, or ``None`` if dropped."""

        self._seq += 1
        seq = self._seq
        self.sent += 1
        reason = self.reachable(src, dst)
        if reason is not None:
            self.dropped += 1
            self.trace.record(self.now, "", "drop", seq=seq, src=src, dst=dst,
                              reason=reason, msg=message.summary())
            return None
        if self.options.drop_rate > 0.0 and self.rng.random() < self.options.drop_rate:
            self.dropped += 1
            self.trace.record(self.now, "", "drop", seq=seq, src=src, dst=dst,
                              reason="random", msg=message.summary())
            return None
        delay = self.rng.randint(self.options.min_delay, self.options.max_delay)
        envelope = Envelope(seq=seq, src=src, dst=dst, sent_at=self.now,
                            deliver_at=self.now + delay, message=message)
        self.queue.push(envelope.deliver_at, "deliver", envelope)
        self.trace.record(self.now, "", "send", seq=seq, src=src, dst=dst,
                          at=envelope.deliver_at, msg=message.summary())
        if self.options.dup_rate > 0.0 and self.rng.random() < self.options.dup_rate:
            self._seq += 1
            extra = self.rng.randint(0, self.options.dup_extra_delay)
            twin = Envelope(seq=self._seq, src=src, dst=dst, sent_at=self.now,
                            deliver_at=envelope.deliver_at + extra, message=message, duplicate_of=seq)
            self.queue.push(twin.deliver_at, "deliver", twin)
            self.duplicated += 1
            self.trace.record(self.now, "", "dup", seq=twin.seq, of=seq, src=src, dst=dst, at=twin.deliver_at)
        return envelope

    def deliver_due(self, now: int) -> list[Envelope]:
        """Everything due at or before ``now``, minus deliveries to nodes
        that are down (those are dropped and traced)."""

        self.now = now
        out: list[Envelope] = []
        for event in self.queue.pop_due(now):
            envelope: Envelope = event.payload
            if envelope.dst in self.down:
                self.dropped += 1
                self.trace.record(now, "", "drop", seq=envelope.seq, src=envelope.src, dst=envelope.dst,
                                  reason="dst_down_at_delivery", msg=envelope.message.summary())
                continue
            self.delivered += 1
            self.trace.record(now, "", "deliver", seq=envelope.seq, src=envelope.src, dst=envelope.dst,
                              sent=envelope.sent_at, msg=envelope.message.summary())
            out.append(envelope)
        return out

    def advance(self, now: int) -> None:
        self.now = now

    @property
    def pending(self) -> int:
        return len(self.queue)

    def describe(self) -> str:
        part = "none" if self.groups is None else "|".join(",".join(sorted(g)) for g in self.groups)
        return (
            f"network sent={self.sent} delivered={self.delivered} dropped={self.dropped} "
            f"dup={self.duplicated} pending={self.pending} partition={part} "
            f"blocked={len(self.blocked)} down={sorted(self.down)}"
        )

    def stats(self) -> dict[str, int]:
        return {"sent": self.sent, "delivered": self.delivered, "dropped": self.dropped,
                "duplicated": self.duplicated, "pending": self.pending}
