"""The wire protocol, as frozen dataclasses.

Every message carries ``term`` first, because the first thing every receiver
does is compare terms (``SPEC.md`` section 2.1). The classes are frozen so a
duplicated or delayed envelope cannot be mutated in flight by the receiver
of its twin.

Serialisation is explicit (``to_dict`` / ``message_from_dict``) rather than
``pickle`` or ``asdict`` because the trace format is part of the contract:
``tools/replay_trace.py`` compares traces produced by different versions of
the code, and a field renamed in a dataclass must show up as a trace
divergence, not as a silently different pickle.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

from .log import Entry, entry_from_dict


@dataclass(frozen=True)
class Message:
    """Base class. ``kind`` is the wire name and the trace name."""

    term: int

    @property
    def kind(self) -> str:
        return KIND_BY_CLASS[type(self)]

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind}
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name == "entries":
                value = [entry.to_dict() for entry in value]
            out[f.name] = value
        return out

    def summary(self) -> str:
        """One short line for the text trace."""

        return f"{self.kind}(t={self.term})"


@dataclass(frozen=True)
class RequestVote(Message):
    """A candidate (or a pre-candidate) asking for a vote.

    ``pre_vote`` distinguishes the two phases. In a pre-vote ``term`` is the
    term the sender *would* adopt if it won — its current term plus one —
    and the sender has not changed its own persistent state. A real vote
    request carries the term the sender has already adopted and persisted.
    """

    candidate_id: str
    last_log_index: int
    last_log_term: int
    pre_vote: bool = False

    def summary(self) -> str:
        phase = "prevote" if self.pre_vote else "vote"
        return (
            f"{self.kind}[{phase}](t={self.term} from={self.candidate_id} "
            f"last={self.last_log_index}/{self.last_log_term})"
        )


@dataclass(frozen=True)
class RequestVoteResponse(Message):
    """The voter's answer. ``term`` is the voter's current term, which in a
    pre-vote may be higher than the request's; the candidate uses it to step
    down without having disturbed anyone."""

    voter_id: str
    granted: bool
    pre_vote: bool = False

    def summary(self) -> str:
        phase = "prevote" if self.pre_vote else "vote"
        verdict = "granted" if self.granted else "denied"
        return f"{self.kind}[{phase}](t={self.term} from={self.voter_id} {verdict})"


@dataclass(frozen=True)
class AppendEntries(Message):
    """Replication and heartbeat. An empty ``entries`` is a heartbeat; there
    is no separate heartbeat message because the follower's checks are the
    same either way."""

    leader_id: str
    prev_log_index: int
    prev_log_term: int
    entries: tuple[Entry, ...] = field(default_factory=tuple)
    leader_commit: int = 0

    def summary(self) -> str:
        return (
            f"{self.kind}(t={self.term} from={self.leader_id} "
            f"prev={self.prev_log_index}/{self.prev_log_term} n={len(self.entries)} "
            f"commit={self.leader_commit})"
        )


@dataclass(frozen=True)
class AppendEntriesResponse(Message):
    """The follower's answer.

    On success ``match_index`` is the index of the last entry the follower
    now knows it shares with the leader. On failure ``conflict_term`` and
    ``conflict_index`` are the hints of ``SPEC.md`` section 3.4, which let
    the leader skip a whole term of mismatched entries per round trip
    instead of one entry.
    """

    follower_id: str
    success: bool
    match_index: int = 0
    conflict_index: int = 0
    conflict_term: int = 0

    def summary(self) -> str:
        if self.success:
            return f"{self.kind}(t={self.term} from={self.follower_id} ok match={self.match_index})"
        return (
            f"{self.kind}(t={self.term} from={self.follower_id} reject "
            f"conflict={self.conflict_index}/{self.conflict_term})"
        )


@dataclass(frozen=True)
class InstallSnapshot(Message):
    """One chunk of a snapshot (``SPEC.md`` section 6, declared). The
    message type exists so traces and the network can carry it; no node
    sends it until ``tidewater.snapshot`` is implemented."""

    leader_id: str
    last_included_index: int
    last_included_term: int
    offset: int
    data: bytes
    done: bool

    def to_dict(self) -> dict[str, Any]:
        out = super().to_dict()
        out["data"] = self.data.hex()
        return out

    def summary(self) -> str:
        return (
            f"{self.kind}(t={self.term} from={self.leader_id} "
            f"last={self.last_included_index}/{self.last_included_term} off={self.offset} "
            f"len={len(self.data)} done={self.done})"
        )


@dataclass(frozen=True)
class InstallSnapshotResponse(Message):
    """Acknowledges a chunk. ``offset`` is the next byte the follower expects,
    so a leader resuming after a crash mid-transfer can pick up where the
    follower is rather than where the leader remembers being."""

    follower_id: str
    offset: int
    done: bool = False

    def summary(self) -> str:
        return f"{self.kind}(t={self.term} from={self.follower_id} next={self.offset} done={self.done})"


@dataclass(frozen=True)
class TimeoutNow(Message):
    """Leadership transfer (``SPEC.md`` section 7, declared): asks the
    receiver to start an election immediately, skipping the pre-vote. Carried
    by the protocol for membership change; not sent by the seed."""

    leader_id: str

    def summary(self) -> str:
        return f"{self.kind}(t={self.term} from={self.leader_id})"


KIND_BY_CLASS: dict[type, str] = {
    RequestVote: "RequestVote",
    RequestVoteResponse: "RequestVoteResponse",
    AppendEntries: "AppendEntries",
    AppendEntriesResponse: "AppendEntriesResponse",
    InstallSnapshot: "InstallSnapshot",
    InstallSnapshotResponse: "InstallSnapshotResponse",
    TimeoutNow: "TimeoutNow",
}

CLASS_BY_KIND: dict[str, type] = {kind: cls for cls, kind in KIND_BY_CLASS.items()}

#: The closed set of message kinds, in protocol order.
MESSAGE_KINDS: tuple[str, ...] = tuple(KIND_BY_CLASS.values())


def message_from_dict(data: dict[str, Any]) -> Message:
    """Inverse of :meth:`Message.to_dict`."""

    kind = data.get("kind")
    cls = CLASS_BY_KIND.get(kind)  # type: ignore[arg-type]
    if cls is None:
        raise ValueError(f"unknown message kind {kind!r}; the protocol knows {MESSAGE_KINDS}")
    payload = {k: v for k, v in data.items() if k != "kind"}
    if cls is AppendEntries:
        payload["entries"] = tuple(entry_from_dict(e) for e in payload.get("entries", ()))
    if cls is InstallSnapshot:
        payload["data"] = bytes.fromhex(payload.get("data", ""))
    return cls(**payload)


@dataclass(frozen=True)
class Envelope:
    """A message in flight: who sent it, to whom, when it was sent and when
    the network decided it arrives. ``seq`` is the network's send counter
    and is the tie-break for same-tick deliveries."""

    seq: int
    src: str
    dst: str
    sent_at: int
    deliver_at: int
    message: Message
    duplicate_of: int | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {
            "seq": self.seq,
            "src": self.src,
            "dst": self.dst,
            "sent_at": self.sent_at,
            "deliver_at": self.deliver_at,
            "message": self.message.to_dict(),
        }
        if self.duplicate_of is not None:
            out["duplicate_of"] = self.duplicate_of
        return out

    def summary(self) -> str:
        dup = f" dup-of={self.duplicate_of}" if self.duplicate_of is not None else ""
        return f"#{self.seq} {self.src}->{self.dst} {self.message.summary()}{dup}"
