"""The placement ring: consistent hashing with virtual nodes.

Ownership of a key is decided here and nowhere else. A plan is a snapshot of
the ring plus the membership epoch it was built under; :class:`Planner`
publishes new plans and every write path asks the *current* plan who owns a
key. Reading the ring from a cached plan is correct only while that plan is
current, which is the invariant the rebalance path has to keep.

Ring construction
-----------------
Each physical replica gets ``vnodes`` virtual nodes. A vnode's position is
``digest(f"{replica}#{index}")`` reduced to a 64-bit integer, and the ring is
the sorted list of ``(position, replica)`` pairs. A key maps to the replica of
the first vnode whose position is **greater than or equal to** the key's
digest, wrapping to position zero when the key sorts past the last vnode.

The wrap is part of the contract. Dropping it silently moves every key whose
digest exceeds the largest vnode position to a shard that does not hold it,
and that is exactly the class of defect a rebalance can introduce.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable, Sequence

DEFAULT_VNODES = 64
RING_BITS = 64
_RING_MASK = (1 << RING_BITS) - 1


def position(token: str) -> int:
    """A stable 64-bit position for a vnode or key token."""

    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & _RING_MASK


@dataclass(frozen=True)
class VNode:
    position: int
    replica: str
    index: int

    @property
    def token(self) -> str:
        return f"{self.replica}#{self.index}"


@dataclass(frozen=True)
class Ring:
    """An immutable hash ring over replica identifiers."""

    replicas: tuple[str, ...]
    vnodes: int = DEFAULT_VNODES
    points: tuple[VNode, ...] = field(default=())

    @classmethod
    def build(cls, replicas: Sequence[str] | Iterable[str], *, vnodes: int = DEFAULT_VNODES) -> "Ring":
        members = tuple(sorted(set(replicas)))
        if not members:
            raise ValueError("a ring needs at least one replica")
        if vnodes < 1:
            raise ValueError("vnodes must be positive")
        points = sorted(
            (
                VNode(position=position(f"{replica}#{index}"), replica=replica, index=index)
                for replica in members
                for index in range(vnodes)
            ),
            key=lambda node: (node.position, node.replica),
        )
        return cls(replicas=members, vnodes=vnodes, points=tuple(points))

    def __len__(self) -> int:
        return len(self.replicas)

    def owner(self, key: str) -> str:
        """The replica that owns ``key``: first vnode at or after the key, wrapping."""

        target = position(key)
        low = 0
        high = len(self.points)
        while low < high:
            middle = (low + high) // 2
            if self.points[middle].position < target:
                low = middle + 1
            else:
                high = middle
        if low == len(self.points):
            low = 0
        return self.points[low].replica

    def owners(self, key: str, count: int) -> tuple[str, ...]:
        """The primary plus the next ``count - 1`` distinct replicas, in ring order."""

        if count < 1:
            raise ValueError("count must be at least one")
        chosen: list[str] = []
        target = position(key)
        ordered = sorted(self.points, key=lambda node: (node.position, node.replica))
        start = 0
        for index, node in enumerate(ordered):
            if node.position >= target:
                start = index
                break
        for offset in range(len(ordered)):
            node = ordered[(start + offset) % len(ordered)]
            if node.replica not in chosen:
                chosen.append(node.replica)
            if len(chosen) == min(count, len(self.replicas)):
                break
        return tuple(chosen)

    def keys_on(self, replica: str) -> tuple[int, int]:
        """(number of vnodes, approximate key share) that would move off ``replica``."""

        held = sum(1 for node in self.points if node.replica == replica)
        return held, int(1_000_000 * held / max(1, len(self.points)))

    def fingerprint(self) -> str:
        hasher = hashlib.blake2b(digest_size=8)
        for node in self.points:
            hasher.update(f"{node.position}:{node.replica};".encode("utf-8"))
        return hasher.hexdigest()
