"""Placement plans: ring plus epoch, published as an immutable snapshot.

A plan is the answer to "where does key K live, under which epoch". The
cluster keeps exactly one *current* plan. Rebalancing builds a new plan,
streams the moved keys, and only then publishes it.

The trap this module is designed to hold: a plan is **a value, not a live
view**. Nothing mutates a published plan in place; a caller that keeps a
reference to plan ``P`` and then asks it a question after the cluster has
moved on is asking ``P`` to answer for ``P+1``, and the answer will be wrong.
The only supported way to ask "who owns K now" is to ask the *current* plan
at the moment of the question, which :class:`PlacementService` provides and
nothing else does.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable

from .ring import Ring

DEFAULT_VNODES = 64


@dataclass(frozen=True)
class Plan:
    """An immutable placement: which replicas exist, and who owns a key."""

    epoch: int
    ring: Ring
    replicas: tuple[str, ...]

    @classmethod
    def build(cls, epoch: int, replicas: Iterable[str], *, vnodes: int = DEFAULT_VNODES) -> "Plan":
        members = tuple(sorted(set(replicas)))
        if not members:
            raise ValueError("a plan needs at least one replica")
        return cls(epoch=epoch, ring=Ring.build(members, vnodes=vnodes), replicas=members)

    def owner(self, key: str) -> str:
        return self.ring.owner(key)

    def replicas_for(self, key: str, count: int) -> tuple[str, ...]:
        return self.ring.owners(key, count)

    def fingerprint(self) -> str:
        digest = hashlib.blake2b(digest_size=8)
        digest.update(f"e{self.epoch}|{self.ring.fingerprint()}".encode("utf-8"))
        return digest.hexdigest()

    def moved(self, other: "Plan") -> dict[str, list[str]]:
        """Keys' primary owner that differs between ``other`` and this plan.

        Returns ``{owner: [keys]}`` for a *sampled* key space; the full
        migration uses the same method with the key set it is actually moving.
        """

        moved: dict[str, list[str]] = {}
        for key, owner in other.owners_by(self.replicas, sample=64).items():
            current = self.owner(key)
            if current != owner:
                moved.setdefault(owner, []).append(key)
        for group in moved.values():
            group.sort()
        return moved

    def owners_by(self, replicas: tuple[str, ...], *, sample: int = 64) -> dict[str, str]:
        """A deterministic sample of (key -> owner) under this plan."""

        picked: dict[str, str] = {}
        seed = 0
        for replica in replicas:
            for index in range(max(1, sample // max(1, len(replicas)))):
                token = f"{replica}:probe:{seed}"
                seed += 1
                picked[token] = self.owner(token)
        return picked


class PlacementService:
    """Holds the current plan and publishes new ones atomically."""

    def __init__(self, epoch: int, replicas: Iterable[str], *, vnodes: int = DEFAULT_VNODES) -> None:
        self.current = Plan.build(epoch, replicas, vnodes=vnodes)

    def owner(self, key: str) -> str:
        """Who owns ``key`` right now. The only supported way to ask."""

        return self.current.owner(key)

    def replicas_for(self, key: str, count: int) -> tuple[str, ...]:
        return self.current.replicas_for(key, count)

    def publish(self, plan: Plan) -> None:
        """Make ``plan`` the current one.

        Publication is the moment old plans stop being answers. Callers that
        still hold a reference to the old plan have not been told; the
        contract is that they must not ask it again, and the rebalance path is
        the one that arranges for nobody to ask it.
        """

        if plan.epoch < self.current.epoch:
            raise ValueError(
                f"cannot publish epoch {plan.epoch} after epoch {self.current.epoch}"
            )
        self.current = plan

    def epoch(self) -> int:
        return self.current.epoch

    def fingerprint(self) -> str:
        return self.current.fingerprint()
