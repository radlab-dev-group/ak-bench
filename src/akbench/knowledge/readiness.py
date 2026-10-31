"""Knowledge-base readiness before a replay (plan section 17).

The end of a session is not the end of the knowledge work: writes are
asynchronous and indexing happens in a separate worker. Starting a replay
before indexing settles measures a knowledge base that was not there yet, and
the result looks like a null effect of knowledge rather than a race.

So readiness is a separate, explicit check with a status, and a replay is
gated on it. The default probe reports ``unsupported`` rather than optimistic:
on the shared external router there is no readback to ask (``/knowledge/stats``
is refused by the access policy and no per-plugin counter is exported, see
``docs/ROUTER_INTEGRATION.md`` section 7), and an unverified knowledge base is
not the same thing as a ready one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from akbench.core.time import utc_now
from akbench.knowledge.sessions import LearningSession


class ReadinessStatus(StrEnum):
    """What can honestly be said about the knowledge base before a replay."""

    READY = "ready"
    NOT_READY = "not_ready"
    UNVERIFIED = "unverified"
    UNSUPPORTED = "unsupported"

    @property
    def may_replay(self) -> bool:
        """Only a confirmed ready knowledge base may be replayed against."""
        return self is ReadinessStatus.READY


@runtime_checkable
class KbReadinessProbe(Protocol):
    """A way to ask a knowledge base whether it has caught up."""

    probe_id: str

    def check(self, session: LearningSession) -> KbReadiness:
        """State what the probe observed about writes and indexing."""
        ...


@dataclass(frozen=True)
class KbReadiness:
    """One readiness observation, with the evidence behind it.

    ``writes_settled`` and ``indexing_settled`` stay ``None`` when the probe
    cannot tell: a missing answer is not an answer of "yes".
    """

    status: ReadinessStatus
    probe_id: str | None = None
    writes_settled: bool | None = None
    indexing_settled: bool | None = None
    checked_at: str | None = None
    evidence: str | None = None
    note: str | None = None

    @property
    def confirmed(self) -> bool:
        return self.status is ReadinessStatus.READY

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "probe": self.probe_id,
            "writes_settled": self.writes_settled,
            "indexing_settled": self.indexing_settled,
            "checked_at": self.checked_at,
            "evidence": self.evidence,
            "note": self.note,
        }


@dataclass(frozen=True)
class NoReadbackProbe:
    """The honest default: this deployment cannot read knowledge-base state."""

    probe_id: str = "none"

    def check(self, session: LearningSession) -> KbReadiness:
        return KbReadiness(
            status=ReadinessStatus.UNSUPPORTED,
            probe_id=self.probe_id,
            checked_at=utc_now().isoformat(),
            note=(
                "no readback of the knowledge base is available: the router refuses "
                "/knowledge reads and exports no per-plugin counter, so readiness "
                "cannot be confirmed (docs/ROUTER_INTEGRATION.md section 7)"
            ),
        )


@dataclass(frozen=True)
class ReplayGate:
    """The decision taken before a replay run starts.

    ``blocked`` is the point of the gate; ``allow_unverified`` can release it,
    but the replay is then marked as not evidence-grade in its own record, so
    a reader of the result sees that the knowledge base was never confirmed.
    """

    allowed: bool
    blocked: bool
    readiness: KbReadiness
    allow_unverified: bool = False
    reason: str | None = None

    @property
    def evidence_grade(self) -> str:
        if self.readiness.confirmed:
            return "verified"
        return "unverified" if self.allowed else "not_run"

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "blocked": self.blocked,
            "allow_unverified": self.allow_unverified,
            "evidence_grade": self.evidence_grade,
            "reason": self.reason,
            "readiness": self.readiness.as_dict(),
        }


def build_readiness_gate(
    session: LearningSession,
    probe: KbReadinessProbe | None = None,
    *,
    allow_unverified: bool = False,
) -> ReplayGate:
    """Ask the probe (if any) and decide whether a replay may start.

    A learning session that produced no knowledge is a reason to block on its
    own: replaying against an empty knowledge base measures the absence of
    data, not the effect of knowledge.
    """
    readiness = (probe or NoReadbackProbe()).check(session)

    if not session.tasks:
        return ReplayGate(
            allowed=False,
            blocked=True,
            readiness=readiness,
            reason="the learning session produced no knowledge to replay against",
        )

    if readiness.confirmed:
        return ReplayGate(
            allowed=True,
            blocked=False,
            readiness=readiness,
            reason="the knowledge base reported writes and indexing settled",
        )

    if allow_unverified:
        return ReplayGate(
            allowed=True,
            blocked=False,
            readiness=readiness,
            allow_unverified=True,
            reason=(
                f"readiness is {readiness.status.value}; the replay runs anyway and is "
                "recorded as unverified"
            ),
        )

    return ReplayGate(
        allowed=False,
        blocked=True,
        readiness=readiness,
        reason=(
            f"readiness is {readiness.status.value}: a replay against an unconfirmed "
            "knowledge base is not started (plan section 17)"
        ),
    )
