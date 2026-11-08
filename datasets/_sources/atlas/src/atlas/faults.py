"""Deterministic crash injection.

The recovery paths cannot be tested by killing processes: a benchmark run has
to reproduce the same crash twice, and it has to do so without threads,
timers or sleeps. This module supplies the seams.

A :class:`CrashPlan` names the points at which a simulated crash may land.
Reaching a point raises :class:`SimulatedCrash`, which is *not* an
:class:`~atlas.errors.AtlasError` — it is control flow, and the store must
not convert it into a failure response. Points are named after the moment
they interrupt, so a scenario reads as an English sentence::

    plan = CrashPlan(at="mid_frame")            # die inside a frame write
    plan = CrashPlan(after="release_current")   # die just after publishing

The set of points is fixed. Adding one is a change to the crash contract and
every recovery scenario has to say what it now expects.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class SimulatedCrash(BaseException):
    """Raised instead of returning. Inherits from BaseException so that the
    broad ``except Exception`` handlers on the write path cannot swallow it."""


#: Every point a crash may land on.
CRASH_POINTS = (
    "before_append",       # nothing reached the log
    "mid_frame",           # a partial frame is on disk
    "after_append",        # records durable, COMMIT not written
    "after_commit",        # the whole transaction is durable
    "before_snapshot",     # compaction started, no file written
    "after_snapshot",      # snapshot file exists, CURRENT not moved
    "release_current",     # CURRENT renamed: the publication decision
    "after_release",       # published, pruning not done
    "before_replay",       # recovery started
    "after_replay",        # recovery finished
)


@dataclass
class CrashPlan:
    """Where to die, and how many times."""

    at: str = ""
    times: int = 1
    #: Points already consumed.
    fired: int = 0
    log: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.at and self.at not in CRASH_POINTS:
            raise ValueError(
                f"unknown crash point {self.at!r}; the contract knows {CRASH_POINTS}"
            )
        if self.times < 1:
            raise ValueError("times must be at least one")

    def active(self, point: str) -> bool:
        return bool(self.at) and point == self.at and self.fired < self.times

    def hit(self, point: str) -> None:
        """Raise if the plan names this point and still has credit."""

        if not self.active(point):
            return
        self.fired += 1
        self.log.append(point)
        raise SimulatedCrash(f"simulated crash at {point} (hit {self.fired}/{self.times})")

    def describe(self) -> str:
        if not self.at:
            return "no crash planned"
        return f"crash at {self.at} x{self.times}, fired {self.fired}"


#: A plan that never fires, which is what production passes.
NO_CRASH = CrashPlan()
