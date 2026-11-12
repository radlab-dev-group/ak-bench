"""Logical time.

There is exactly one notion of "now" in a simulation: the **tick**, an
integer owned by :class:`LogicalClock`. Nothing in the package reads the wall
clock, sleeps, or runs on a thread. Everything that happens at a tick happens
in the order the cluster driver asks for it, and the driver asks in a fixed
order (``SPEC.md`` section 1), which is what makes two runs with the same
seed produce the same trace byte for byte.

Each node sees time through a :class:`NodeClock`. A node clock advances by
``rate`` local ticks for every global tick and starts ``offset`` ticks ahead
of the global clock. A fast node clock is how the simulator models a server
whose election timer fires early; a schedule's ``skew`` action changes both
fields at a chosen tick.

:class:`EventQueue` is a priority queue keyed by ``(at, seq)``. The sequence
number is the tie-break: two events due at the same tick pop in the order
they were pushed, never in dictionary or hash order.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any, Iterator

from .errors import ConfigurationError


class LogicalClock:
    """The global tick counter. Starts at zero and only goes forward."""

    def __init__(self, start: int = 0) -> None:
        if start < 0:
            raise ConfigurationError("the clock cannot start before tick 0")
        self._now = start

    @property
    def now(self) -> int:
        return self._now

    def advance(self, ticks: int = 1) -> int:
        """Move forward by ``ticks`` (at least one) and return the new now."""

        if ticks < 1:
            raise ConfigurationError("the clock advances by at least one tick")
        self._now += ticks
        return self._now

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"LogicalClock(now={self._now})"


@dataclass
class NodeClock:
    """A node's view of time: ``offset + rate * global``.

    ``rate`` is an integer so that local time stays integral and a trace can
    print it without rounding. ``rate`` must be at least one: a node whose
    clock stands still would never time out, which is not a server, it is a
    rock.
    """

    rate: int = 1
    offset: int = 0
    _local: int = 0

    def __post_init__(self) -> None:
        self.set_skew(self.rate, self.offset)
        self._local = self.offset

    @property
    def now(self) -> int:
        return self._local

    def set_skew(self, rate: int | None = None, offset: int | None = None) -> None:
        """Change the skew from this moment on. The local clock does not jump
        backwards: an offset decrease only slows the apparent passage of time
        until the new offset is caught up."""

        if rate is not None:
            if rate < 1:
                raise ConfigurationError("a node clock rate must be at least 1")
            self.rate = rate
        if offset is not None:
            if offset < 0:
                raise ConfigurationError("a node clock offset cannot be negative")
            self.offset = offset

    def tick(self) -> int:
        """Advance by one global tick; return the new local time."""

        self._local += self.rate
        return self._local

    def describe(self) -> str:
        if self.rate == 1 and self.offset == 0:
            return "no skew"
        return f"rate={self.rate} offset={self.offset}"


@dataclass(order=True)
class Event:
    """Something due at tick ``at``. Ordered by ``(at, seq)`` only; the kind
    and payload never take part in ordering."""

    at: int
    seq: int
    kind: str = field(compare=False)
    payload: Any = field(compare=False, default=None)


class EventQueue:
    """A deterministic priority queue of :class:`Event`."""

    def __init__(self) -> None:
        self._heap: list[Event] = []
        self._seq = 0

    def __len__(self) -> int:
        return len(self._heap)

    def push(self, at: int, kind: str, payload: Any = None) -> Event:
        if at < 0:
            raise ConfigurationError("an event cannot be scheduled before tick 0")
        event = Event(at=at, seq=self._seq, kind=kind, payload=payload)
        self._seq += 1
        heapq.heappush(self._heap, event)
        return event

    def peek(self) -> Event | None:
        return self._heap[0] if self._heap else None

    def pop_due(self, now: int) -> list[Event]:
        """Pop every event with ``at <= now`` in ``(at, seq)`` order."""

        due: list[Event] = []
        while self._heap and self._heap[0].at <= now:
            due.append(heapq.heappop(self._heap))
        return due

    def drain(self) -> list[Event]:
        """Pop everything, in order. Used when a partition heals or a node
        restarts and the driver wants to re-examine pending deliveries."""

        out: list[Event] = []
        while self._heap:
            out.append(heapq.heappop(self._heap))
        return out

    def remove_if(self, predicate) -> int:
        """Drop every event the predicate accepts; return how many were
        dropped. Rebuilds the heap, which is fine at the sizes a simulation
        reaches."""

        keep = [event for event in self._heap if not predicate(event)]
        removed = len(self._heap) - len(keep)
        heapq.heapify(keep)
        self._heap = keep
        return removed

    def __iter__(self) -> Iterator[Event]:
        return iter(sorted(self._heap))
