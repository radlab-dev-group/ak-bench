"""Cluster membership: the fixed configuration, and the declared change.

.. note::
   **Membership change is not implemented.** :class:`Configuration` below is
   real and is what every node uses to count majorities. Everything from
   :class:`JointConfiguration` down declares the contract for joint
   consensus; every method that would do work raises
   :class:`~tidewater.errors.FeatureNotImplemented`. The contract is
   complete and normative — ``SPEC.md`` section 7 is the acceptance rule;
   ``docs/adr/ADR-0007`` is why joint consensus and not single-server
   changes — and an implementation is judged against it, not against these
   stubs.

The seed runs with a fixed configuration: the set of voters named by the
schedule, stored durably on every node (``Storage.voters``) so that a node
restarting alone knows whom to ask for votes. Majorities are always counted
over the *current configuration* a node holds, never over "the nodes that
answered" or "the nodes that exist in the cluster object" — that distinction
is invisible with fixed membership and is the whole point once membership
changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .errors import ConfigurationError, FeatureNotImplemented


@dataclass(frozen=True)
class Configuration:
    """A set of voting members. Immutable; a change produces a new one."""

    voters: frozenset[str]

    def __post_init__(self) -> None:
        if not self.voters:
            raise ConfigurationError("a configuration needs at least one voter")
        for voter in self.voters:
            if not isinstance(voter, str) or not voter:
                raise ConfigurationError("voter ids are non-empty strings")

    @classmethod
    def of(cls, voters: Iterable[str]) -> "Configuration":
        return cls(frozenset(voters))

    @property
    def size(self) -> int:
        return len(self.voters)

    @property
    def majority_size(self) -> int:
        """Strictly more than half: 3 of 5, 2 of 3, 1 of 1, 2 of 2."""

        return self.size // 2 + 1

    def contains(self, node_id: str) -> bool:
        return node_id in self.voters

    def has_majority(self, acks: Iterable[str]) -> bool:
        """True if ``acks`` — restricted to members of *this* configuration —
        form a majority. Acks from non-members are ignored, which is what
        makes a vote from a server that was removed harmless."""

        counted = {a for a in acks if a in self.voters}
        return len(counted) >= self.majority_size

    def sorted_voters(self) -> tuple[str, ...]:
        return tuple(sorted(self.voters))

    def peers_of(self, node_id: str) -> tuple[str, ...]:
        return tuple(v for v in self.sorted_voters() if v != node_id)

    def describe(self) -> str:
        return "{" + ",".join(self.sorted_voters()) + "}"


def disjoint_quorums_possible(a: Configuration, b: Configuration) -> bool:
    """Can a majority of ``a`` and a majority of ``b`` be chosen with no
    server in common? This is the question the ``membership_split``
    invariant asks of every pair of configurations alive at the same time.

    A quorum of ``a`` that wants to avoid ``b`` uses the servers only in
    ``a`` first and then dips into the intersection; likewise for ``b``.
    Disjoint quorums exist exactly when the two dips together fit in the
    intersection.
    """

    only_a = len(a.voters - b.voters)
    only_b = len(b.voters - a.voters)
    shared = len(a.voters & b.voters)
    dip_a = max(0, a.majority_size - only_a)
    dip_b = max(0, b.majority_size - only_b)
    return dip_a + dip_b <= shared


# ---------------------------------------------------------------------------
# Declared, not implemented: joint consensus.
# ---------------------------------------------------------------------------

#: Configuration entry payload kinds (``Entry.kind == "config"``). A joint
#: entry carries both sets; a final entry carries only the new one.
CONFIG_JOINT = "joint"
CONFIG_FINAL = "final"


@dataclass(frozen=True)
class JointConfiguration:
    """``C_old,new``: decisions need a majority of *both* configurations.

    Contract (``SPEC.md`` 7.2): while the joint entry is in a node's log —
    committed or not — that node counts votes and replication acks against
    ``old`` and against ``new`` separately and requires both majorities. A
    node that only holds ``C_old`` counts against ``old`` alone. A node
    whose latest configuration entry is the final ``C_new`` counts against
    ``new`` alone.
    """

    old: Configuration
    new: Configuration

    def has_majority(self, acks: Iterable[str]) -> bool:  # pragma: no cover - contract stub
        """Both majorities, from the same set of acks."""

        raise FeatureNotImplemented("joint consensus is not implemented")

    @property
    def all_voters(self) -> frozenset[str]:
        return self.old.voters | self.new.voters

    def describe(self) -> str:
        return f"joint({self.old.describe()} -> {self.new.describe()})"


@dataclass
class MembershipChange:
    """The leader-side state machine of one change (``SPEC.md`` 7.3-7.6).

    Phases, in order, each a method below:

    1. ``begin(new_voters)`` — refuse if a change is already in flight;
       otherwise start **catch-up** for the servers in ``new - old``: they
       receive ``AppendEntries`` as non-voting learners until each one is
       within ``catch_up_rounds`` of the leader's last index.
    2. ``propose_joint()`` — append the ``C_old,new`` entry; from the moment
       it is appended the leader uses :class:`JointConfiguration` for every
       majority decision.
    3. ``on_joint_committed()`` — append the ``C_new`` entry.
    4. ``on_final_committed()`` — the change is complete. If the leader is
       not in ``C_new`` it steps down **now, after** committing ``C_new``,
       and not before (``ADR-0007`` records the reason: an earlier step-down
       leaves the joint entry uncommitted with no one obliged to finish it).

    A crash at any phase restarts from the log: the latest configuration
    entry in the log, committed or not, is the configuration in force.
    """

    old: Configuration
    new: Configuration | None = None
    phase: str = "idle"
    learners: dict[str, int] = field(default_factory=dict)
    catch_up_rounds: int = 3

    def begin(self, new_voters: Iterable[str]) -> None:  # pragma: no cover - contract stub
        raise FeatureNotImplemented("membership change is not implemented")

    def learner_caught_up(self, node_id: str, match_index: int, leader_last: int) -> bool:  # pragma: no cover
        """True if ``node_id`` has replicated to within one append of the
        leader's last index (``leader_last - match_index <= max_entries``)."""

        raise FeatureNotImplemented("membership change is not implemented")

    def propose_joint(self) -> dict:  # pragma: no cover - contract stub
        """The payload for the joint ``config`` entry:
        ``{"config": "joint", "old": [...], "new": [...]}``."""

        raise FeatureNotImplemented("membership change is not implemented")

    def on_joint_committed(self) -> dict:  # pragma: no cover - contract stub
        """The payload for the final ``config`` entry: ``{"config": "final", "new": [...]}``."""

        raise FeatureNotImplemented("membership change is not implemented")

    def on_final_committed(self, leader_id: str) -> bool:  # pragma: no cover - contract stub
        """Finish; return True if ``leader_id`` must step down because it is
        not in ``C_new``."""

        raise FeatureNotImplemented("membership change is not implemented")


def configuration_from_entry_payload(payload: dict) -> Configuration | JointConfiguration:  # pragma: no cover
    """Decode a ``config`` entry's payload into the configuration it puts in
    force. A node applies this to the *latest* config entry in its log —
    committed or not — on every append and on restart."""

    raise FeatureNotImplemented("membership change is not implemented")
