"""Seeded randomness, one stream per consumer.

The simulator uses randomness in exactly two places: a node's election
timeout and the network's delay/drop/duplicate decisions. Both must be
reproducible from a single integer seed, and — this is the part that
matters — a decision made by one consumer must not shift the decisions of
another. If every node drew from one shared ``random.Random``, adding a
heartbeat on node ``n1`` would change the timeout node ``n3`` draws next, and
a schedule that reproduced an election storm would stop reproducing it the
moment someone fixed an unrelated bug. ``docs/adr/ADR-0002`` records the
decision; this module implements it.

:class:`SeedTree` derives child seeds by hashing ``(root_seed, *labels)`` with
SHA-256, so ``tree.stream("n1", "election")`` is the same generator on every
machine and in every Python version, independent of ``hash()`` randomisation.
"""

from __future__ import annotations

import hashlib
import random
from typing import Iterable


def derive_seed(root: int, *labels: str) -> int:
    """A 64-bit child seed for ``labels`` under ``root``. Pure and stable."""

    h = hashlib.sha256()
    h.update(str(int(root)).encode("ascii"))
    for label in labels:
        h.update(b"/")
        h.update(str(label).encode("utf-8"))
    return int.from_bytes(h.digest()[:8], "big")


class Stream:
    """A thin wrapper over ``random.Random`` that remembers its label and
    counts draws, so a trace can say "the 14th draw on n1/election".

    Only the methods the simulator needs are exposed; adding a method here
    is cheap, but every draw changes the sequence for every later draw on
    the same stream, so callers should not draw "just to look".
    """

    def __init__(self, seed: int, label: str) -> None:
        self.seed = seed
        self.label = label
        self._rng = random.Random(seed)
        self.draws = 0

    def randrange(self, start: int, stop: int | None = None) -> int:
        self.draws += 1
        return self._rng.randrange(start, stop)

    def randint(self, a: int, b: int) -> int:
        self.draws += 1
        return self._rng.randint(a, b)

    def random(self) -> float:
        self.draws += 1
        return self._rng.random()

    def choice(self, seq):
        self.draws += 1
        return self._rng.choice(seq)

    def shuffle(self, seq: list) -> None:
        self.draws += 1
        self._rng.shuffle(seq)

    def election_timeout(self, base: int) -> int:
        """Draw a timeout in ``[base, 2 * base)``.

        This is *the* randomised timeout rule of ``SPEC.md`` section 2.3. The
        lower bound is inclusive and the upper bound is exclusive; the width
        of the window equals the base so that two nodes' windows always
        overlap by at least half, which is what keeps split votes rare
        without making the slowest node wait forever.
        """

        if base < 1:
            raise ValueError("the election timeout base must be at least 1 tick")
        return base + self.randrange(base)

    def describe(self) -> str:
        return f"{self.label} seed={self.seed} draws={self.draws}"


class SeedTree:
    """Derives and caches named streams from one root seed."""

    def __init__(self, root: int) -> None:
        self.root = int(root)
        self._streams: dict[tuple[str, ...], Stream] = {}

    def seed_for(self, *labels: str) -> int:
        return derive_seed(self.root, *labels)

    def stream(self, *labels: str) -> Stream:
        """The stream for ``labels``; the same object on every call."""

        key = tuple(str(label) for label in labels)
        stream = self._streams.get(key)
        if stream is None:
            stream = Stream(self.seed_for(*key), "/".join(key))
            self._streams[key] = stream
        return stream

    def node_streams(self, node_ids: Iterable[str]) -> dict[str, Stream]:
        """Election streams for a set of nodes, created in sorted order so the
        cache is filled identically no matter how the caller iterates."""

        return {node_id: self.stream(node_id, "election") for node_id in sorted(node_ids)}

    def describe(self) -> list[str]:
        return [stream.describe() for _, stream in sorted(self._streams.items())]
