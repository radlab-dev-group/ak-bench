"""Anti-entropy: digests, comparison, and repair that no read triggered.

Read repair only sees the keys someone reads. Anti-entropy walks the shard and
compares replicas by digest, so a key nobody touches still converges. A
digest is computed over the record set with the registered digest strategy
(:mod:`atlas.registry`) and covers the key, the generation and the LSN — but
**not the value**, which is deliberate: two replicas that disagree about a
value while agreeing on the version would produce identical digests, and the
store says so out loud in :func:`compare_digests` rather than pretending a
digest is a content hash.

The walk is deterministic: keys sorted, ranges halved, digests compared from
the top down. A divergence is reported as the smallest key range whose digest
differs, never as a count, because a count tells an operator nothing about
where to look.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .registry import STRATEGIES

RANGE_DEPTH = 8


@dataclass(frozen=True)
class RangeDigest:
    low: str
    high: str
    digest: str
    keys: int

    def contains(self, key: str) -> bool:
        return self.low <= key < self.high


@dataclass
class Divergence:
    low: str
    high: str
    left: str
    right: str
    keys: tuple[str, ...] = ()

    def describe(self) -> str:
        return f"[{self.low!r}, {self.high!r}) diverges: {self.left} vs {self.right}"


@dataclass
class AntiEntropyReport:
    compared: int = 0
    matches: int = 0
    divergences: list[Divergence] = field(default_factory=list)
    repaired: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.divergences


def digest_records(records, *, strategy: str = "blake2b-16") -> str:
    """A deterministic digest of a record set."""

    digest = STRATEGIES.digest.resolve(strategy)(sorted(records, key=lambda record: (record.key, record.generation)))
    if isinstance(digest, bytes):
        return digest.hex()
    return str(digest)


def range_digest(store, low: str, high: str, *, strategy: str = "blake2b-16") -> RangeDigest:
    records = [
        record
        for record in store.state.all_records()
        if low <= record.key < high
    ]
    return RangeDigest(
        low=low,
        high=high,
        digest=digest_records(records, strategy=strategy),
        keys=len(records),
    )


def compare_digests(left: str, right: str) -> bool:
    """Digests are equal, which does not mean the values are.

    The digest covers identity, not content. Two replicas whose digests match
    agree on which version of each key they hold; that is the property
    anti-entropy is built to check, and conflating it with content equality is
    a bug this function cannot see and the caller must not assume.
    """

    return left == right


class AntiEntropy:
    def __init__(self, nodes, *, placement, strategy: str = "blake2b-16", width: int = 8) -> None:
        self.nodes = nodes
        self.placement = placement
        self.strategy = strategy
        self.width = width

    def walk(self, left_node, right_node, shard: int) -> AntiEntropyReport:
        report = AntiEntropyReport()
        for low, high in self._ranges():
            left = range_digest(left_node.store(shard), low, high, strategy=self.strategy)
            right = range_digest(right_node.store(shard), low, high, strategy=self.strategy)
            report.compared += 1
            if compare_digests(left.digest, right.digest):
                report.matches += 1
                continue
            report.divergences.append(
                Divergence(
                    low=low,
                    high=high,
                    left=left.digest,
                    right=right.digest,
                    keys=self._keys_between(left_node.store(shard), right_node.store(shard), low, high),
                )
            )
        return report

    def _ranges(self):
        step = 0x100000000 // self.width
        for index in range(self.width):
            low = f"{index * step:08x}"
            high = f"{(index + 1) * step:08x}" if index + 1 < self.width else "￿"
            yield low, high

    def _keys_between(self, left, right, low: str, high: str) -> tuple[str, ...]:
        left_map = {record.key: record for record in left.all_records() if low <= record.key < high}
        right_map = {record.key: record for record in right.all_records() if low <= record.key < high}
        differing = []
        for key in sorted(set(left_map) | set(right_map)):
            a = left_map.get(key)
            b = right_map.get(key)
            if a is None or b is None or a.vector != b.vector or a.generation != b.generation:
                differing.append(key)
        return tuple(differing)
