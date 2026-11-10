"""One server: follower, pre-candidate, candidate, leader.

The node is a pure state machine over three inputs — ``tick()``, ``receive()``
and ``propose()`` — and one output, the outbox of ``(destination, message)``
pairs the cluster hands to the network. It never calls the network, never
reads the global clock (it has its own :class:`~tidewater.clock.NodeClock`),
and never draws randomness except through the one election stream it was
given. That is what makes a node testable in isolation: a test can feed it
messages by hand and read the outbox.

The rules this module implements are normative in ``SPEC.md``; the section
numbers are quoted at the point of implementation. The ones task authors
most often want to find:

* **2.3 randomised timeout** — ``[T, 2T)`` from the node's own stream, drawn
  afresh at every reset (:meth:`Node._reset_election_timer`);
* **2.4 pre-vote** — a timed-out node first asks "would you vote for me?"
  with ``term + 1`` and changes nothing persistent until a majority says yes
  (:meth:`Node._on_election_timeout`, :meth:`Node._handle_request_vote`);
* **2.7 leader stickiness** — a voter denies a pre-vote while it has heard
  from a leader within the last ``T`` local ticks;
* **3.2 log matching** and **3.3 truncate only on conflict** — delegated to
  :class:`~tidewater.log.RaftLog`;
* **4.1 current-term commit** — a leader advances its commit index only to
  an index whose entry carries the *current* term, counted over a majority
  of the current configuration (:meth:`Node._advance_commit_index`);
* **5.x persistence** — ``current_term``, ``voted_for`` and the log are
  synced before any message that depends on them leaves the outbox.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import snapshot as snapshot_module
from .clock import NodeClock
from .errors import ConfigurationError, NodeDownError, NotLeaderError
from .log import ENTRY_COMMAND, ENTRY_NOOP, Entry, RaftLog
from .membership import Configuration
from .messages import (
    AppendEntries,
    AppendEntriesResponse,
    InstallSnapshot,
    InstallSnapshotResponse,
    Message,
    RequestVote,
    RequestVoteResponse,
    TimeoutNow,
)
from .rng import Stream
from .statemachine import Command, KVStateMachine
from .storage import Storage
from .trace import Trace

FOLLOWER = "follower"
PRE_CANDIDATE = "pre_candidate"
CANDIDATE = "candidate"
LEADER = "leader"

ROLES = (FOLLOWER, PRE_CANDIDATE, CANDIDATE, LEADER)


@dataclass(frozen=True)
class NodeOptions:
    """Per-node tunables. Defaults are the ones the schedule corpus uses.

    ``election_timeout`` is ``T`` of the ``[T, 2T)`` rule. ``heartbeat_interval``
    must be well under ``T``; the schedule validator enforces ``H * 3 <= T``.
    ``compaction_threshold`` of zero disables snapshots, which is the only
    working value in the seed (``SPEC.md`` section 6 is declared, not
    implemented); a positive value makes the node call into
    :mod:`tidewater.snapshot` once the log reaches that many entries, and
    that call raises until the feature exists.
    """

    election_timeout: int = 50
    heartbeat_interval: int = 10
    pre_vote: bool = True
    max_entries_per_append: int = 16
    compaction_threshold: int = 0
    sync_policy: str = "always"

    def __post_init__(self) -> None:
        if self.election_timeout < 3:
            raise ConfigurationError("election_timeout must be at least 3 ticks")
        if self.heartbeat_interval < 1:
            raise ConfigurationError("heartbeat_interval must be at least 1 tick")
        if self.heartbeat_interval * 3 > self.election_timeout:
            raise ConfigurationError("heartbeat_interval * 3 must not exceed election_timeout")
        if self.max_entries_per_append < 1:
            raise ConfigurationError("max_entries_per_append must be at least 1")
        if self.compaction_threshold < 0:
            raise ConfigurationError("compaction_threshold cannot be negative (0 disables)")

    def to_dict(self) -> dict[str, Any]:
        return {
            "election_timeout": self.election_timeout,
            "heartbeat_interval": self.heartbeat_interval,
            "pre_vote": self.pre_vote,
            "max_entries_per_append": self.max_entries_per_append,
            "compaction_threshold": self.compaction_threshold,
            "sync_policy": self.sync_policy,
        }


class Node:
    """A Raft-lite server. See the module docstring for the rule map."""

    def __init__(
        self,
        node_id: str,
        config: Configuration,
        storage: Storage,
        rng: Stream,
        clock: NodeClock,
        trace: Trace,
        options: NodeOptions | None = None,
    ) -> None:
        if not config.contains(node_id):
            raise ConfigurationError(f"{node_id} is not a voter in {config.describe()}")
        self.node_id = node_id
        self.config = config
        self.storage = storage
        self.rng = rng
        self.clock = clock
        self.trace = trace
        self.options = options or NodeOptions()

        self.alive = True
        self.restarts = 0
        self.global_tick = 0
        self.outbox: list[tuple[str, Message]] = []

        self.role = FOLLOWER
        self.leader_id: str | None = None
        self.log: RaftLog = storage.load_log()
        self.state_machine = KVStateMachine()
        self.commit_index = 0
        self.votes: set[str] = set()
        self.prevotes: set[str] = set()
        self.next_index: dict[str, int] = {}
        self.match_index: dict[str, int] = {}
        self.election_deadline = 0
        self.heartbeat_due = 0
        self.last_leader_contact = -self.options.election_timeout
        self.timeouts = 0
        self.elections_started = 0

        self._reset_election_timer()
        self.trace.record(self.global_tick, self.node_id, "start",
                          term=self.current_term, timeout=self.election_deadline - self.clock.now,
                          config=list(self.config.sorted_voters()))

    # -- read-only views ---------------------------------------------------

    @property
    def current_term(self) -> int:
        return self.storage.current_term

    @property
    def voted_for(self) -> str | None:
        return self.storage.voted_for

    @property
    def is_leader(self) -> bool:
        return self.alive and self.role == LEADER

    @property
    def peers(self) -> tuple[str, ...]:
        return self.config.peers_of(self.node_id)

    def drain_outbox(self) -> list[tuple[str, Message]]:
        out, self.outbox = self.outbox, []
        return out

    def describe(self) -> str:
        return (
            f"{self.node_id} {self.role} term={self.current_term} vote={self.voted_for} "
            f"leader={self.leader_id} log={self.log.last_index}/{self.log.last_term} "
            f"commit={self.commit_index} applied={self.state_machine.last_applied} "
            f"{'up' if self.alive else 'DOWN'}"
        )

    # -- lifecycle ---------------------------------------------------------

    def crash(self) -> None:
        """Lose everything volatile. Persistent state is whatever storage
        made durable (``SPEC.md`` 5.3)."""

        if not self.alive:
            raise NodeDownError(f"{self.node_id} is already down")
        self.alive = False
        self.storage.crash()
        self.outbox.clear()
        self.trace.record(self.global_tick, self.node_id, "crash",
                          term=self.current_term, role=self.role,
                          last_index=self.log.last_index, commit=self.commit_index,
                          lost_writes=self.storage.lost_writes)

    def restart(self) -> None:
        """Come back as a follower from durable state. Commit index and the
        applied state are rebuilt (``SPEC.md`` 5.4)."""

        if self.alive:
            raise NodeDownError(f"{self.node_id} is not down")
        self.alive = True
        self.restarts += 1
        self.role = FOLLOWER
        self.leader_id = None
        self.log = self.storage.load_log()
        self.state_machine = KVStateMachine()
        self.commit_index = 0
        self.votes = set()
        self.prevotes = set()
        self.next_index = {}
        self.match_index = {}
        self.last_leader_contact = self.clock.now - self.options.election_timeout
        self._reset_election_timer()
        self.trace.record(self.global_tick, self.node_id, "restart",
                          term=self.current_term, vote=self.voted_for,
                          last_index=self.log.last_index, last_term=self.log.last_term,
                          timeout=self.election_deadline - self.clock.now)

    def set_skew(self, rate: int | None = None, offset: int | None = None) -> None:
        self.clock.set_skew(rate, offset)
        self.trace.record(self.global_tick, self.node_id, "skew", rate=self.clock.rate, offset=self.clock.offset)

    # -- the tick ------------------------------------------------------------

    def tick(self, global_tick: int) -> None:
        """One unit of global time. Advances the local clock, fires the
        election timer or the heartbeat timer, applies committed entries."""

        self.global_tick = global_tick
        if not self.alive:
            return
        now = self.clock.tick()
        if self.role == LEADER:
            if now >= self.heartbeat_due:
                self._broadcast_append()
        elif now >= self.election_deadline:
            self._on_election_timeout()
        self._apply_committed()

    # -- client path ---------------------------------------------------------

    def propose(self, command: Command) -> Entry:
        """Append a client command (leader only) and replicate it at once."""

        if not self.alive:
            raise NodeDownError(f"{self.node_id} is down")
        if self.role != LEADER:
            raise NotLeaderError(self.node_id, self.leader_id or "")
        entry = Entry(index=self.log.last_index + 1, term=self.current_term,
                      kind=ENTRY_COMMAND, command=command)
        self.log.append(entry)
        self.storage.save_log(self.log)
        self.storage.sync()
        self.match_index[self.node_id] = self.log.last_index
        self.trace.record(self.global_tick, self.node_id, "propose",
                          index=entry.index, term=entry.term, command=command.summary())
        if self.config.size == 1:
            self._advance_commit_index()
        self._broadcast_append()
        self._apply_committed()
        return entry

    # -- receive -------------------------------------------------------------

    def receive(self, src: str, message: Message) -> None:
        if not self.alive:
            return
        if isinstance(message, RequestVote):
            self._handle_request_vote(src, message)
        elif isinstance(message, RequestVoteResponse):
            self._handle_vote_response(src, message)
        elif isinstance(message, AppendEntries):
            self._handle_append_entries(src, message)
        elif isinstance(message, AppendEntriesResponse):
            self._handle_append_response(src, message)
        elif isinstance(message, InstallSnapshot):
            self._handle_install_snapshot(src, message)
        elif isinstance(message, InstallSnapshotResponse):
            self._handle_install_snapshot_response(src, message)
        elif isinstance(message, TimeoutNow):
            self._handle_timeout_now(src, message)
        else:  # pragma: no cover - the protocol is closed
            raise TypeError(f"unknown message {type(message).__name__}")
        self._apply_committed()

    # -- timers ------------------------------------------------------------

    def _reset_election_timer(self) -> None:
        """``SPEC.md`` 2.3: a fresh draw in ``[T, 2T)`` from this node's stream."""

        timeout = self.rng.election_timeout(self.options.election_timeout)
        self.election_deadline = self.clock.now + timeout

    def _heard_from_leader_recently(self) -> bool:
        """``SPEC.md`` 2.7: within the last ``T`` local ticks."""

        if self.leader_id is None:
            return False
        return (self.clock.now - self.last_leader_contact) < self.options.election_timeout

    def _on_election_timeout(self) -> None:
        self.timeouts += 1
        self.trace.record(self.global_tick, self.node_id, "timeout",
                          term=self.current_term, role=self.role, local=self.clock.now)
        if self.config.size == 1:
            self._start_election()
            return
        if self.options.pre_vote:
            self._start_prevote()
        else:
            self._start_election()

    def _start_prevote(self) -> None:
        """``SPEC.md`` 2.4: ask for ``term + 1`` without touching storage."""

        self.role = PRE_CANDIDATE
        self.leader_id = None
        self.prevotes = {self.node_id}
        self._reset_election_timer()
        self.trace.record(self.global_tick, self.node_id, "prevote_start",
                          term=self.current_term, proposed=self.current_term + 1,
                          last_index=self.log.last_index, last_term=self.log.last_term)
        request = RequestVote(term=self.current_term + 1, candidate_id=self.node_id,
                              last_log_index=self.log.last_index, last_log_term=self.log.last_term,
                              pre_vote=True)
        for peer in self.peers:
            self.outbox.append((peer, request))

    def _start_election(self) -> None:
        """``SPEC.md`` 2.5: increment the term, vote for self, persist, ask."""

        term = self.current_term + 1
        self.storage.set_term(term, self.node_id)
        self.storage.sync()
        self.role = CANDIDATE
        self.leader_id = None
        self.votes = {self.node_id}
        self.prevotes = set()
        self.elections_started += 1
        self._reset_election_timer()
        self.trace.record(self.global_tick, self.node_id, "election_start",
                          term=term, last_index=self.log.last_index, last_term=self.log.last_term)
        if self.config.has_majority(self.votes):
            self._become_leader()
            return
        request = RequestVote(term=term, candidate_id=self.node_id,
                              last_log_index=self.log.last_index, last_log_term=self.log.last_term)
        for peer in self.peers:
            self.outbox.append((peer, request))

    # -- role transitions ----------------------------------------------------

    def _become_follower(self, term: int, leader_id: str | None = None, reason: str = "") -> None:
        """Adopt ``term`` (persisting it if higher) and drop any candidacy or
        leadership. Resets the election timer."""

        previous_role = self.role
        if term > self.current_term:
            self.storage.set_term(term, None)
            self.storage.sync()
        self.role = FOLLOWER
        self.leader_id = leader_id
        self.votes = set()
        self.prevotes = set()
        self.next_index = {}
        self.match_index = {}
        self._reset_election_timer()
        if previous_role != FOLLOWER or reason:
            self.trace.record(self.global_tick, self.node_id, "step_down",
                              term=self.current_term, was=previous_role, reason=reason or "higher_term",
                              leader=leader_id or "")

    def _become_leader(self) -> None:
        """``SPEC.md`` 2.8: initialise replication state and append a no-op
        in the new term so that older entries can be committed under 4.1."""

        self.role = LEADER
        self.leader_id = self.node_id
        self.votes = set()
        self.prevotes = set()
        for peer in self.peers:
            self.next_index[peer] = self.log.last_index + 1
            self.match_index[peer] = 0
        noop = Entry(index=self.log.last_index + 1, term=self.current_term, kind=ENTRY_NOOP)
        self.log.append(noop)
        self.storage.save_log(self.log)
        self.storage.sync()
        self.match_index[self.node_id] = self.log.last_index
        self.trace.record(self.global_tick, self.node_id, "leader",
                          term=self.current_term, noop_index=noop.index,
                          last_index=self.log.last_index, commit=self.commit_index)
        if self.config.size == 1:
            self._advance_commit_index()
        self._broadcast_append()

    # -- votes ---------------------------------------------------------------

    def _handle_request_vote(self, src: str, msg: RequestVote) -> None:
        if msg.pre_vote:
            self._handle_prevote_request(src, msg)
            return
        if msg.term > self.current_term:
            self._become_follower(msg.term, reason="vote_request")
        if msg.term < self.current_term:
            self._deny_vote(src, msg, "stale_term")
            return
        if self.voted_for not in (None, msg.candidate_id):
            self._deny_vote(src, msg, "already_voted")
            return
        if not self.log.is_up_to_date(msg.last_log_index, msg.last_log_term):
            self._deny_vote(src, msg, "log_behind")
            return
        # Grant. Persist the vote before the reply leaves (SPEC 5.2).
        if self.voted_for is None:
            self.storage.set_term(self.current_term, msg.candidate_id)
            self.storage.sync()
        self._reset_election_timer()
        self.trace.record(self.global_tick, self.node_id, "vote", term=self.current_term,
                          candidate=msg.candidate_id, granted=True, reason="granted")
        self.outbox.append((src, RequestVoteResponse(term=self.current_term, voter_id=self.node_id, granted=True)))

    def _deny_vote(self, src: str, msg: RequestVote, reason: str) -> None:
        self.trace.record(self.global_tick, self.node_id, "vote", term=self.current_term,
                          candidate=msg.candidate_id, granted=False, reason=reason)
        self.outbox.append((src, RequestVoteResponse(term=self.current_term, voter_id=self.node_id, granted=False)))

    def _handle_prevote_request(self, src: str, msg: RequestVote) -> None:
        """``SPEC.md`` 2.4 and 2.7. Never changes persistent state."""

        if self.role == LEADER:
            reason, granted = "is_leader", False
        elif msg.term < self.current_term:
            reason, granted = "stale_term", False
        elif self._heard_from_leader_recently():
            reason, granted = "leader_lease", False
        elif not self.log.is_up_to_date(msg.last_log_index, msg.last_log_term):
            reason, granted = "log_behind", False
        else:
            reason, granted = "granted", True
        self.trace.record(self.global_tick, self.node_id, "prevote", term=self.current_term,
                          candidate=msg.candidate_id, proposed=msg.term, granted=granted, reason=reason)
        self.outbox.append((src, RequestVoteResponse(term=self.current_term, voter_id=self.node_id,
                                                     granted=granted, pre_vote=True)))

    def _handle_vote_response(self, src: str, msg: RequestVoteResponse) -> None:
        if msg.pre_vote:
            if self.role != PRE_CANDIDATE:
                return
            if not msg.granted:
                if msg.term > self.current_term:
                    self._become_follower(msg.term, reason="prevote_denied")
                return
            self.prevotes.add(msg.voter_id)
            if self.config.has_majority(self.prevotes):
                self._start_election()
            return
        if msg.term > self.current_term:
            self._become_follower(msg.term, reason="vote_response")
            return
        if self.role != CANDIDATE or msg.term != self.current_term or not msg.granted:
            return
        self.votes.add(msg.voter_id)
        if self.config.has_majority(self.votes):
            self._become_leader()

    # -- replication: leader side -----------------------------------------

    def _broadcast_append(self) -> None:
        for peer in self.peers:
            self._send_append(peer)
        self.heartbeat_due = self.clock.now + self.options.heartbeat_interval

    def _send_append(self, peer: str) -> None:
        next_index = self.next_index.get(peer, self.log.last_index + 1)
        prev_index = next_index - 1
        prev_term = self.log.term_at(prev_index)
        if prev_term is None:
            # The follower needs entries we compacted away: SPEC 6.4.
            self._send_snapshot(peer)
            return
        entries = self.log.slice(next_index, self.options.max_entries_per_append)
        msg = AppendEntries(term=self.current_term, leader_id=self.node_id,
                            prev_log_index=prev_index, prev_log_term=prev_term,
                            entries=entries, leader_commit=self.commit_index)
        self.outbox.append((peer, msg))

    def _handle_append_response(self, src: str, msg: AppendEntriesResponse) -> None:
        if msg.term > self.current_term:
            self._become_follower(msg.term, reason="append_response")
            return
        if self.role != LEADER or msg.term != self.current_term:
            return
        follower = msg.follower_id
        if msg.success:
            if msg.match_index > self.match_index.get(follower, 0):
                self.match_index[follower] = msg.match_index
            self.next_index[follower] = max(self.next_index.get(follower, 1), msg.match_index + 1)
            self._advance_commit_index()
            if self.next_index[follower] <= self.log.last_index:
                self._send_append(follower)
            return
        # Rejected: use the conflict hint (SPEC 3.4), then retry at once.
        current = self.next_index.get(follower, self.log.last_index + 1)
        if msg.conflict_term > 0:
            last_of_term = None
            for entry in reversed(self.log.entries()):
                if entry.term == msg.conflict_term:
                    last_of_term = entry.index
                    break
                if entry.term < msg.conflict_term:
                    break
            candidate = last_of_term + 1 if last_of_term is not None else msg.conflict_index
        else:
            candidate = msg.conflict_index
        new_next = max(self.log.first_index, min(candidate, current - 1))
        self.next_index[follower] = new_next
        self._send_append(follower)

    def _advance_commit_index(self) -> None:
        """``SPEC.md`` 4.1: the largest ``N > commit_index`` such that a
        majority of the current configuration has ``match_index >= N`` and
        ``log[N].term == current_term``."""

        for index in range(self.log.last_index, self.commit_index, -1):
            if self.log.term_at(index) != self.current_term:
                # Entries of earlier terms are committed indirectly, once an
                # entry of this term above them is (ADR-0004).
                continue
            acks = {self.node_id} | {p for p, m in self.match_index.items() if m >= index}
            if self.config.has_majority(acks):
                self._set_commit_index(index, "majority")
                return

    def _set_commit_index(self, index: int, how: str) -> None:
        if index <= self.commit_index:
            return
        previous = self.commit_index
        self.commit_index = index
        self.trace.record(self.global_tick, self.node_id, "commit",
                          term=self.current_term, index=index, previous=previous,
                          entry_term=self.log.term_at(index), how=how)

    # -- replication: follower side --------------------------------------

    def _handle_append_entries(self, src: str, msg: AppendEntries) -> None:
        if msg.term < self.current_term:
            self.trace.record(self.global_tick, self.node_id, "reject_append",
                              term=self.current_term, leader=msg.leader_id, reason="stale_term",
                              prev=msg.prev_log_index)
            self.outbox.append((src, AppendEntriesResponse(term=self.current_term, follower_id=self.node_id,
                                                           success=False)))
            return
        if msg.term > self.current_term or self.role != FOLLOWER:
            self._become_follower(msg.term, leader_id=msg.leader_id, reason="append_from_leader")
        self.leader_id = msg.leader_id
        self.last_leader_contact = self.clock.now
        self._reset_election_timer()

        accepted, truncated, appended, match = self.log.append_from_leader(
            msg.prev_log_index, msg.prev_log_term, msg.entries
        )
        if not accepted:
            conflict_index, conflict_term = self.log.conflict_hint(msg.prev_log_index)
            self.trace.record(self.global_tick, self.node_id, "reject_append",
                              term=self.current_term, leader=msg.leader_id, reason="log_mismatch",
                              prev=msg.prev_log_index, prev_term=msg.prev_log_term,
                              conflict_index=conflict_index, conflict_term=conflict_term)
            self.outbox.append((src, AppendEntriesResponse(
                term=self.current_term, follower_id=self.node_id, success=False,
                conflict_index=conflict_index, conflict_term=conflict_term)))
            return
        if truncated:
            self.trace.record(self.global_tick, self.node_id, "truncate",
                              term=self.current_term, removed=truncated, last_index=self.log.last_index)
        if appended or truncated:
            self.storage.save_log(self.log)
            self.storage.sync()
        if appended:
            self.trace.record(self.global_tick, self.node_id, "append",
                              term=self.current_term, count=appended,
                              first=msg.entries[0].index if msg.entries else 0,
                              last_index=self.log.last_index, last_term=self.log.last_term)
        if msg.leader_commit > self.commit_index:
            # SPEC 4.3: min(leader_commit, index of last new entry).
            self._set_commit_index(min(msg.leader_commit, match), "leader")
        self.outbox.append((src, AppendEntriesResponse(term=self.current_term, follower_id=self.node_id,
                                                       success=True, match_index=match)))

    # -- apply ---------------------------------------------------------------

    def _apply_committed(self) -> None:
        while self.state_machine.last_applied < self.commit_index:
            index = self.state_machine.last_applied + 1
            entry = self.log.at(index)
            result = self.state_machine.apply(index, entry.command if entry.kind == ENTRY_COMMAND else None)
            self.trace.record(self.global_tick, self.node_id, "apply",
                              index=index, term=entry.term, entry=entry.kind,
                              result=result.summary(), digest=self.state_machine.digest()[:12])
        self._maybe_compact()

    # -- snapshots (declared) --------------------------------------------

    def _maybe_compact(self) -> None:
        threshold = self.options.compaction_threshold
        if threshold and len(self.log) >= threshold and self.state_machine.last_applied > self.log.base_index:
            snapshot_module.take_snapshot(self, snapshot_module.SnapshotPolicy(threshold=threshold))

    def _send_snapshot(self, peer: str) -> None:
        snapshot_module.send_snapshot_chunk(self, peer, offset=0)

    def _handle_install_snapshot(self, src: str, msg: InstallSnapshot) -> None:
        if msg.term < self.current_term:
            self.outbox.append((src, InstallSnapshotResponse(term=self.current_term, follower_id=self.node_id,
                                                             offset=0)))
            return
        if msg.term > self.current_term or self.role != FOLLOWER:
            self._become_follower(msg.term, leader_id=msg.leader_id, reason="snapshot_from_leader")
        self.leader_id = msg.leader_id
        self.last_leader_contact = self.clock.now
        self._reset_election_timer()
        snapshot_module.receive_snapshot_chunk(self, src, msg)

    def _handle_install_snapshot_response(self, src: str, msg: InstallSnapshotResponse) -> None:
        if msg.term > self.current_term:
            self._become_follower(msg.term, reason="snapshot_response")
            return
        if self.role != LEADER or msg.term != self.current_term:
            return
        snapshot_module.on_snapshot_ack(self, src, msg)

    def _handle_timeout_now(self, src: str, msg: TimeoutNow) -> None:
        """Leadership transfer (declared with membership change). A node that
        receives this from its current leader starts a real election now."""

        if msg.term < self.current_term or self.role == LEADER:
            return
        if msg.term > self.current_term:
            self._become_follower(msg.term, reason="timeout_now")
        self.trace.record(self.global_tick, self.node_id, "timeout", term=self.current_term,
                          role=self.role, local=self.clock.now, forced_by=msg.leader_id)
        self._start_election()
