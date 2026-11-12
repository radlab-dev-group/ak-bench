"""Exception hierarchy.

Every error the simulator raises on purpose derives from
:class:`TidewaterError`, so a driver can tell a defect in the simulator from
a defect in the thing being simulated: the first is a plain Python error,
the second is one of the classes below. The one exception that matters most,
:class:`~tidewater.invariants.SafetyViolation`, lives next to the checkers
that raise it; it is re-exported here for convenience of ``except`` clauses.
"""

from __future__ import annotations


class TidewaterError(Exception):
    """Base class for everything the simulator raises deliberately."""


class ConfigurationError(TidewaterError):
    """A cluster or node option is outside its documented domain."""


class ScheduleError(TidewaterError):
    """A schedule file is malformed, names an unknown action, or refers to a
    node the cluster does not have."""


class NotLeaderError(TidewaterError):
    """A client command was offered to a node that is not the leader.

    Carries ``leader_hint`` — the leader the node last heard from, or an empty
    string — so a client driver can redirect without guessing.
    """

    def __init__(self, node_id: str, leader_hint: str = "") -> None:
        self.node_id = node_id
        self.leader_hint = leader_hint
        hint = f" (leader hint: {leader_hint})" if leader_hint else ""
        super().__init__(f"{node_id} is not the leader{hint}")


class NodeDownError(TidewaterError):
    """An operation was attempted on a crashed node."""


class StorageError(TidewaterError):
    """The persistent state of a node is inconsistent with the contract in
    ``SPEC.md`` section 5 — for example a vote recorded for a term that was
    never persisted."""


class TraceError(TidewaterError):
    """A trace file could not be read, or two traces are not comparable."""


class FeatureNotImplemented(TidewaterError, NotImplementedError):
    """Raised by the declared-but-unimplemented surfaces (snapshots, membership
    change). Inherits from ``NotImplementedError`` so that callers who only
    know the standard library name still catch it."""
