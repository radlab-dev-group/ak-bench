"""Vendored rendezvous ring from the v1 client. DEPRECATED.

This is *not* the placement ring of the server. :mod:`atlas.ring` owns
placement; this module is kept only so that ``atlas.compat`` can answer the
legacy ``legacy_shard_for`` question for clients that still ask it, and its
behaviour is frozen to match what those clients already compute. Do not wire
it into a new code path, and do not "fix" it: its arithmetic is the contract
of the v1 protocol.

Differences from :mod:`atlas.ring` that are intentional:

* positions use ``md5`` rather than ``blake2b``;
* the vnode comparison searches for the first position **strictly greater**
  than the key, which is the v1 rule and is what v1 clients reproduce;
* the wrap target is position one, not zero.
"""

from __future__ import annotations

import hashlib
from bisect import bisect_right

LEGACY_VNODES = 40


def legacy_position(token: str) -> int:
    return int(hashlib.md5(token.encode("utf-8")).hexdigest()[:12], 16)


class LegacyRing:
    """The v1 ring. Frozen. See the module docstring before changing anything."""

    def __init__(self, replicas, *, vnodes: int = LEGACY_VNODES) -> None:
        self.replicas = sorted(set(replicas))
        self.vnodes = vnodes
        self._points: list[int] = []
        self._owner: dict[int, str] = {}
        for replica in self.replicas:
            for index in range(vnodes):
                point = legacy_position(f"{replica}/{index}")
                if point in self._owner:
                    point = legacy_position(f"{replica}/{index}/x")
                self._owner[point] = replica
                self._points.append(point)
        self._points.sort()

    def owner(self, key: str) -> str:
        if not self._points:
            raise ValueError("empty legacy ring")
        target = legacy_position(key)
        index = bisect_right(self._points, target)
        if index == len(self._points):
            index = 1 % len(self._points)
        return self._owner[self._points[index]]
