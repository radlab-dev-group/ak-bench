"""The driver: nodes, network, schedule and invariants in one loop.

``Cluster.step()`` is the whole of the simulator's time model and the order
of its phases is normative (``SPEC.md`` 1.2), because changing it changes
every trace:

1. **actions** — every schedule action due at this tick fires, in file
   order. ``propose`` actions join the pending queue;
2. **proposals** — each pending proposal is offered to the leader, if there
   is exactly one live leader; otherwise it waits (traced once per tick as
   ``propose_pending`` only when it first fails, to keep the trace readable);
3. **deliveries** — the network hands over every envelope due at this tick,
   in ``(deliver_at, seq)`` order, and each node processes its message;
4. **ticks** — every node, in id order, advances its local clock and fires
   its timers;
5. **sends** — every node's outbox, in id order, is drained into the
   network, which stamps delivery ticks;
6. **invariants** — the monitor inspects every live node; a violation is
   traced as ``violation`` and raised;
7. the global clock advances.

Phase 5 after phases 3 and 4 means a reply to a message delivered at tick
``t`` is sent at tick ``t`` and arrives no earlier than ``t + min_delay``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .clock import LogicalClock, NodeClock
from .errors import NodeDownError, NotLeaderError, ScheduleError
from .invariants import InvariantMonitor, SafetyViolation
from .membership import Configuration
from .network import Network
from .node import Node
from .rng import SeedTree
from .schedule import Action, Schedule
from .statemachine import Command, command_from_dict
from .storage import Storage
from .trace import Trace


@dataclass
class PendingProposal:
    command: Command
    since: int
    attempts: int = 0
    reported: bool = False


@dataclass
class RunResult:
    schedule: str
    seed: int
    ticks: int
    digest: str
    events: int
    violation: SafetyViolation | None
    leaders_by_term: dict[int, str]
    commit_indexes: dict[str, int]
    applied: dict[str, int]
    network: dict[str, int]
    proposals: dict[str, int]
    trace: Trace = field(repr=False)

    @property
    def ok(self) -> bool:
        return self.violation is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedule": self.schedule,
            "seed": self.seed,
            "ticks": self.ticks,
            "digest": self.digest,
            "events": self.events,
            "violation": None if self.violation is None else {
                "kind": self.violation.kind, "detail": self.violation.detail, "tick": self.violation.tick,
            },
            "leaders_by_term": {str(k): v for k, v in sorted(self.leaders_by_term.items())},
            "commit_indexes": dict(sorted(self.commit_indexes.items())),
            "applied": dict(sorted(self.applied.items())),
            "network": self.network,
            "proposals": self.proposals,
        }

    def render(self) -> str:
        lines = [
            f"schedule   {self.schedule}",
            f"seed       {self.seed}",
            f"ticks      {self.ticks}",
            f"events     {self.events}",
            f"digest     {self.digest}",
            f"leaders    " + ", ".join(f"t{t}={n}" for t, n in sorted(self.leaders_by_term.items())),
            f"commits    " + ", ".join(f"{n}={c}" for n, c in sorted(self.commit_indexes.items())),
            f"applied    " + ", ".join(f"{n}={c}" for n, c in sorted(self.applied.items())),
            f"network    " + ", ".join(f"{k}={v}" for k, v in self.network.items()),
            f"proposals  " + ", ".join(f"{k}={v}" for k, v in self.proposals.items()),
        ]
        if self.violation is not None:
            lines.append(f"VIOLATION  {self.violation}")
        return "\n".join(lines)


class Cluster:
    """Build from a :class:`~tidewater.schedule.Schedule`; drive with
    :meth:`step` or :meth:`run`."""

    def __init__(
        self,
        schedule: Schedule,
        seed: int | None = None,
        trace: Trace | None = None,
        check_invariants: bool = True,
        stop_on_violation: bool = True,
    ) -> None:
        schedule.validate()
        self.schedule = schedule
        self.seed = schedule.seed if seed is None else int(seed)
        self.trace = trace if trace is not None else Trace()
        self.check_invariants = check_invariants
        self.stop_on_violation = stop_on_violation

        self.clock = LogicalClock()
        self.seeds = SeedTree(self.seed)
        self.config = Configuration.of(schedule.nodes)
        self.network = Network(self.seeds.stream("network"), self.trace, schedule.network_options)
        self.monitor = InvariantMonitor()
        self.nodes: dict[str, Node] = {}
        self.trace.record(0, "", "schedule", name=schedule.name, seed=self.seed, ticks=schedule.ticks,
                          nodes=list(schedule.nodes), digest=schedule.digest()[:16])
        for node_id in schedule.nodes:
            storage = Storage(node_id, schedule.nodes, sync_policy=schedule.node_options.sync_policy)
            self.nodes[node_id] = Node(
                node_id=node_id,
                config=self.config,
                storage=storage,
                rng=self.seeds.stream(node_id, "election"),
                clock=NodeClock(),
                trace=self.trace,
                options=schedule.node_options,
            )
        self._actions: list[Action] = schedule.expanded_actions()
        self._action_cursor = 0
        self.pending: list[PendingProposal] = []
        self.proposed = 0
        self.accepted = 0
        self.given_up = 0
        self.violation: SafetyViolation | None = None
        self.finished = False

    # -- views ---------------------------------------------------------------

    @property
    def now(self) -> int:
        return self.clock.now

    def node(self, node_id: str) -> Node:
        try:
            return self.nodes[node_id]
        except KeyError:
            raise ScheduleError(f"no node {node_id!r} in {sorted(self.nodes)}") from None

    def live_leaders(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.is_leader]

    def leader(self) -> Node | None:
        """The unique live leader of the highest term, or ``None``."""

        leaders = self.live_leaders()
        if not leaders:
            return None
        return max(leaders, key=lambda n: n.current_term)

    def describe(self) -> str:
        lines = [f"tick {self.now}: {self.network.describe()}"]
        lines.extend("  " + n.describe() for n in self.nodes.values())
        return "\n".join(lines)

    # -- the loop --------------------------------------------------------------

    def step(self) -> None:
        if self.finished:
            return
        now = self.clock.now
        self.network.advance(now)
        self._fire_actions(now)
        self._offer_proposals(now)
        for envelope in self.network.deliver_due(now):
            self.nodes[envelope.dst].receive(envelope.src, envelope.message)
        for node in self.nodes.values():
            node.tick(now)
        for node in self.nodes.values():
            for dst, message in node.drain_outbox():
                self.network.send(node.node_id, dst, message)
        if self.check_invariants:
            try:
                self.monitor.check(self.nodes.values(), now)
            except SafetyViolation as violation:
                self.violation = violation
                self.trace.record(now, "", "violation", violation=violation.kind, detail=violation.detail)
                if self.stop_on_violation:
                    self.finished = True
                    raise
        self.clock.advance()
        if self.clock.now >= self.schedule.ticks:
            self.finished = True

    def run(self, ticks: int | None = None) -> RunResult:
        """Run to the end of the schedule (or ``ticks`` ticks from now).
        A safety violation stops the run and is reported in the result
        rather than raised, so a driver can still write the trace."""

        target = self.schedule.ticks if ticks is None else min(self.schedule.ticks, self.clock.now + ticks)
        try:
            while not self.finished and self.clock.now < target:
                self.step()
        except SafetyViolation:
            pass
        if self.finished or self.clock.now >= self.schedule.ticks:
            self.trace.record(self.clock.now, "", "end", ticks=self.clock.now,
                              pending=len(self.pending), violation=self.violation.kind if self.violation else "")
        return self.result()

    def result(self) -> RunResult:
        return RunResult(
            schedule=self.schedule.name,
            seed=self.seed,
            ticks=self.clock.now,
            digest=self.trace.digest(),
            events=len(self.trace),
            violation=self.violation,
            leaders_by_term=dict(self.monitor.leaders_by_term),
            commit_indexes={n.node_id: n.commit_index for n in self.nodes.values()},
            applied={n.node_id: n.state_machine.last_applied for n in self.nodes.values()},
            network=self.network.stats(),
            proposals={"offered": self.proposed, "accepted": self.accepted,
                       "pending": len(self.pending), "given_up": self.given_up},
            trace=self.trace,
        )

    # -- phases ------------------------------------------------------------

    def _fire_actions(self, now: int) -> None:
        while self._action_cursor < len(self._actions) and self._actions[self._action_cursor].at <= now:
            action = self._actions[self._action_cursor]
            self._action_cursor += 1
            self.apply_action(action, now)

    def apply_action(self, action: Action, now: int | None = None) -> None:
        """Apply one action immediately. Public so tests can drive faults by
        hand without writing a schedule file."""

        now = self.now if now is None else now
        kind, args = action.kind, action.args
        if kind == "propose":
            self.propose(command_from_dict(args["command"]))
        elif kind == "partition":
            self.network.partition(args["groups"])
        elif kind == "heal":
            self.network.heal()
        elif kind == "isolate":
            self.network.isolate(args["node"], self.nodes)
        elif kind == "block":
            self.network.block(args["src"], args["dst"], bool(args.get("both", True)))
        elif kind == "unblock":
            self.network.unblock(args["src"], args["dst"], bool(args.get("both", True)))
        elif kind == "crash":
            self.crash(args["node"])
        elif kind == "restart":
            self.restart(args["node"])
        elif kind == "skew":
            rate = args.get("rate")
            offset = args.get("offset")
            self.node(args["node"]).set_skew(None if rate is None else int(rate), None if offset is None else int(offset))
        elif kind == "network":
            self.network.set_options(**args)
        elif kind == "workload":
            # Unroll into proposes; the ones due now fire now, the rest join
            # the action list in tick order.
            probe = Schedule(name="workload", nodes=self.schedule.nodes, seed=0, ticks=now + 10 ** 9,
                             actions=[Action(at=now, kind="workload", args=args)])
            for expanded in probe.expanded_actions():
                if expanded.at == now:
                    self.apply_action(expanded, now)
                else:
                    self._actions.append(expanded)
            self._actions.sort(key=lambda a: a.at)
        else:  # pragma: no cover - validated at load
            raise ScheduleError(f"unknown action {kind!r}")

    def propose(self, command: Command) -> None:
        self.proposed += 1
        self.pending.append(PendingProposal(command=command, since=self.now))

    def crash(self, node_id: str) -> None:
        node = self.node(node_id)
        if not node.alive:
            raise NodeDownError(f"{node_id} is already down at tick {self.now}")
        node.global_tick = self.now
        node.crash()
        self.network.mark_down(node_id)

    def restart(self, node_id: str) -> None:
        node = self.node(node_id)
        if node.alive:
            raise NodeDownError(f"{node_id} is not down at tick {self.now}")
        self.network.mark_up(node_id)
        node.global_tick = self.now
        node.restart()

    def _offer_proposals(self, now: int) -> None:
        if not self.pending:
            return
        leader = self.leader()
        still: list[PendingProposal] = []
        for proposal in self.pending:
            proposal.attempts += 1
            if leader is not None:
                try:
                    leader.propose(proposal.command)
                    self.accepted += 1
                    continue
                except (NotLeaderError, NodeDownError):
                    pass
            if not proposal.reported:
                proposal.reported = True
                self.trace.record(now, "", "propose_pending", command=proposal.command.summary(),
                                  since=proposal.since, leaders=[n.node_id for n in self.live_leaders()])
            limit = self.schedule.give_up_after
            if limit and now - proposal.since >= limit:
                self.given_up += 1
                self.trace.record(now, "", "propose_rejected", command=proposal.command.summary(),
                                  since=proposal.since, attempts=proposal.attempts)
                continue
            still.append(proposal)
        self.pending = still


def run_schedule(schedule: Schedule, seed: int | None = None, ticks: int | None = None,
                 trace: Trace | None = None) -> RunResult:
    """Convenience: build a cluster and run it. ``ticks`` overrides the
    schedule's length (shorter or longer); actions beyond the new length
    are simply never reached."""

    if ticks is not None and ticks != schedule.ticks:
        kept = [a for a in schedule.expanded_actions() if a.at < int(ticks)]
        schedule = Schedule(
            name=schedule.name, description=schedule.description, nodes=schedule.nodes,
            seed=schedule.seed, ticks=int(ticks), actions=kept,
            node_options=schedule.node_options, network_options=schedule.network_options,
            give_up_after=schedule.give_up_after,
        )
    cluster = Cluster(schedule, seed=seed, trace=trace)
    return cluster.run()
