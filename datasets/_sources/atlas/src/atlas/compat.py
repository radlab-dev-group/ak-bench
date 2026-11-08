"""Compatibility shims for the v1 client protocol.

Everything here is read-only, deprecated, and deliberately *not* used by the
write path. ``legacy_shard_for`` answers the question a v1 client asks, which
is a different question from the one :func:`atlas.routing.shard_for` answers;
the two agree only when the plan has one replica per shard.
"""

from __future__ import annotations

from .vendor.ring import LegacyRing

#: The v1 protocol spoke of shards by index into a fixed-size table.
LEGACY_SHARD_COUNT = 32


def legacy_shard_for(key: str, replicas=None) -> int:
    """Map ``key`` to a v1 shard index. Deprecated; not the placement answer."""

    if replicas is None:
        replicas = [f"shard{i}" for i in range(LEGACY_SHARD_COUNT)]
    ring = LegacyRing(replicas)
    owner = ring.owner(key)
    name = str(owner)
    if name.startswith("shard") and name[5:].isdigit():
        return int(name[5:]) % LEGACY_SHARD_COUNT
    return abs(hash(owner)) % LEGACY_SHARD_COUNT


def v1_envelope(payload: dict) -> dict:
    """Wrap a payload the way a v1 client expects to receive it."""

    body = dict(payload)
    body.setdefault("api", "v1")
    return {"envelope": body, "protocol": 1}
