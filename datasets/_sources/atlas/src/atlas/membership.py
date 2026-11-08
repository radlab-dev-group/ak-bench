"""Membership and epochs: who is in the cluster, and under which epoch.

An epoch is a number, and the number is the whole point. Every replica knows
the epoch under which it holds a shard; a write admitted at epoch ``E`` is a
write for epoch ``E``; a membership change moves the cluster to epoch
``E+1`` and the old epoch's replicas stop being able to commit or
acknowledge. There is no grace period, no "still settling" window, and no
clock in the comparison: epoch ``E`` is stale the moment the cluster has
epoch ``E+1``.

Two consequences the rest of the store depends on:

* fencing is a **less-than**, never an equality with "recent". A replica at
  ``E-1`` is not "close enough";
* the epoch is carried on the write and re-checked at commit time, not at
  admission time, because that is where a cut-off node comes back.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import EpochMismatchError


@dataclass(frozen=True)
class Member:
    node_id: str
    epoch: int
    alive: bool = True

    def is_stale(self, epoch: int) -> bool:
        return self.epoch < epoch


@dataclass
class Membership:
    epoch: int
    members: dict[str, Member] = field(default_factory=dict)

    def __init__(self, epoch: int, members: dict[str, Member] | None = None) -> None:
        if epoch < 1:
            raise ValueError("epoch starts at one")
        self.epoch = int(epoch)
        self.members = dict(members or {})

    def add(self, node_id: str) -> Member:
        member = Member(node_id=node_id, epoch=self.epoch)
        self.members[node_id] = member
        return member

    def drop(self, node_id: str) -> Member | None:
        return self.members.pop(node_id, None)

    def node(self, node_id: str) -> Member:
        try:
            return self.members[node_id]
        except KeyError as exc:
            raise EpochMismatchError(node_id, 0, self.epoch) from exc

    def advance(self) -> "Membership":
        """Move the cluster one epoch forward; every member's epoch follows."""

        next_epoch = self.epoch + 1
        members = {
            node_id: Member(node_id=node_id, epoch=next_epoch, alive=member.alive)
            for node_id, member in self.members.items()
        }
        return Membership(next_epoch, members)

    def check_epoch(self, node_id: str, offered_epoch: int) -> int:
        """Raise unless ``offered_epoch`` is the current epoch of ``node_id``.

        The check compares against the cluster epoch, not against the member's
        recorded epoch: a member that fell out and came back still carries the
        epoch it was handed, and the cluster has moved on since.
        """

        if offered_epoch != self.epoch:
            raise EpochMismatchError(node_id, offered_epoch, self.epoch)
        return self.epoch

    def alive_nodes(self) -> list[str]:
        return sorted(node_id for node_id, member in self.members.items() if member.alive)
