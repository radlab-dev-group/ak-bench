"""Elapsed time in the terminal, for a run that blocks the CLI.

A managed run spends most of its wall clock before the agent has said anything:
the router instance is launched, its plugin pipeline imports, ``/health`` is
polled until the process answers. Silence that long is indistinguishable from a
hang, so while a run blocks the CLI owns one line and rewrites it every second
with the time spent so far and the phase the run last reported.

The live line goes to a terminal only. A pipe, a log file or a test capture
would collect a line per second of control characters, so there the same facts
are printed once, after the run: when it started, how long it took, and where
the transition log says the time went.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from rich.console import Console

#: How often the live line is rewritten. Below a second it flickers for no
#: information a waiting operator cannot read off a watch.
DEFAULT_INTERVAL = 1.0

#: A phase shorter than this is a bookkeeping step, not a share of the run.
MIN_PHASE_SECONDS = 0.5

_CLEAR_LINE = "\x1b[2K\r"


def format_duration(seconds: float | None) -> str:
    """A duration the way a person reads one: ``4.2s``, ``42s``, ``2m11s``, ``1h02m03s``."""
    if seconds is None:
        return "unknown"
    if seconds < 10:
        return f"{seconds:.1f}s"
    total = round(seconds)
    if total < 60:
        return f"{total}s"
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    return f"{minutes}m{secs:02d}s"


def format_clock(moment: datetime | None) -> str:
    """The wall-clock time a run started, in the operator's local zone."""
    if moment is None:
        return "unknown"
    return moment.astimezone().strftime("%H:%M:%S")


def phase_durations(record: dict[str, Any]) -> list[tuple[str, float]]:
    """Where one run's time went, from the transition log it left behind.

    The interval between two events is the time spent *in* the first event's
    state: the orchestrator enters a state and only then does its work. Steps
    recorded twice (a note logged while the state did not change) are merged,
    and sub-second jumps are dropped — they are the machine moving, not a phase.
    """
    events = record.get("history") or []
    stamps = [_as_datetime(event.get("at")) for event in events]

    durations: list[tuple[str, float]] = []
    for index in range(len(events) - 1):
        start, end = stamps[index], stamps[index + 1]
        if start is None or end is None:
            continue
        delta = (end - start).total_seconds()
        state = str(events[index].get("state"))
        if durations and durations[-1][0] == state:
            durations[-1] = (state, durations[-1][1] + delta)
        else:
            durations.append((state, delta))
    return [(state, seconds) for state, seconds in durations if seconds >= MIN_PHASE_SECONDS]


def format_phases(phases: list[tuple[str, float]]) -> str:
    return ", ".join(f"{state} {format_duration(seconds)}" for state, seconds in phases)


class StepClock:
    """One blocking step: the seconds it has spent, and the phase it reported.

    ``report_phase`` is the hook the run's transition callback writes to; the
    ticker thread only reads it. Assigning a string is atomic enough for a
    display, and the callback must never be able to break a run.
    """

    def __init__(self, label: str = "") -> None:
        self.label = label
        self.phase = ""
        self._started = time.monotonic()

    def report_phase(self, state: str) -> None:
        self.phase = state

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._started

    def line(self) -> str:
        parts = [part for part in (self.label, format_duration(self.elapsed), self.phase) if part]
        return " · ".join(parts)

    @contextmanager
    def running(
        self, console: Console, *, enabled: bool = True, interval: float = DEFAULT_INTERVAL
    ) -> Iterator[StepClock]:
        """Tick the line while the block runs; leave the terminal clean after it."""
        if not enabled or not console.is_terminal:
            yield self
            return

        stream = console.file
        stop = threading.Event()

        def render() -> None:
            try:
                stream.write(f"{_CLEAR_LINE}  {self.line()}")
                stream.flush()
            except (OSError, ValueError):
                # A closed or redirected stream must end the ticker, never the run.
                stop.set()

        def tick() -> None:
            while not stop.wait(interval):
                render()

        render()
        thread = threading.Thread(target=tick, name="akbench-elapsed-clock", daemon=True)
        thread.start()
        try:
            yield self
        finally:
            stop.set()
            thread.join(timeout=interval * 3)
            try:
                stream.write(_CLEAR_LINE)
                stream.flush()
            except (OSError, ValueError):
                pass


def _as_datetime(value: Any) -> datetime | None:
    """Accept what a run record really carries: a datetime, an ISO string, or neither."""
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if moment.tzinfo is None:
        # A naive stamp is compared against aware ones only, and the run log is
        # written in UTC: read it as UTC rather than crashing on the subtraction.
        from datetime import UTC

        moment = moment.replace(tzinfo=UTC)
    return moment
