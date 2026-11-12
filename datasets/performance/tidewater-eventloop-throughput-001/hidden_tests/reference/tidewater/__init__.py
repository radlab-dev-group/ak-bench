"""Tidewater: a deterministic discrete-event simulator of a replicated log.

A small Raft-lite — elections with pre-vote, log replication with the
log-matching rule, commit by majority of the current configuration, a
key-value state machine — driven by logical time and a JSON fault schedule,
with every safety property checked after every tick. No threads, no timers,
no sleeps; randomness only through seeded per-consumer streams.

``SPEC.md`` is the normative contract; ``README.md`` is the map;
``CONTRIBUTING.md`` says which document wins when they disagree.
"""

from .cluster import Cluster, RunResult, run_schedule
from .errors import (
    ConfigurationError,
    FeatureNotImplemented,
    NodeDownError,
    NotLeaderError,
    ScheduleError,
    StorageError,
    TidewaterError,
    TraceError,
)
from .invariants import VIOLATION_KINDS, InvariantMonitor, SafetyViolation
from .schedule import Action, Schedule, load_schedule, schedule_from_dict
from .trace import Trace, first_divergence

__version__ = "1.0.0"

__all__ = [
    "Action",
    "Cluster",
    "ConfigurationError",
    "FeatureNotImplemented",
    "InvariantMonitor",
    "NodeDownError",
    "NotLeaderError",
    "RunResult",
    "SafetyViolation",
    "Schedule",
    "ScheduleError",
    "StorageError",
    "TidewaterError",
    "Trace",
    "TraceError",
    "VIOLATION_KINDS",
    "first_divergence",
    "load_schedule",
    "run_schedule",
    "schedule_from_dict",
    "__version__",
]
