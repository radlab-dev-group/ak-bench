"""Error hierarchy of the Atlas store.

Every error carries a stable ``code`` so that tools and tests can react to
failure classes without string matching. The public API only raises these
types; internal control flow uses ordinary exceptions from the standard
library and converts at the boundary.
"""

from __future__ import annotations


class AtlasError(Exception):
    """Base class of every Atlas error. The code is stable and documented."""

    code = "atlas_error"


class ConfigError(AtlasError):
    code = "config_error"


class UnknownShardError(AtlasError):
    code = "unknown_shard"

    def __init__(self, shard: int, known: frozenset[int]) -> None:
        self.shard = shard
        self.known = known
        super().__init__(f"shard {shard} is not part of the cluster; known shards: {sorted(known)}")


class KeyNotFoundError(AtlasError):
    code = "key_not_found"

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"key not found: {key!r}")


class LeaseError(AtlasError):
    code = "lease_error"


class StaleGenerationError(LeaseError):
    """An acknowledgment or write arrived for a generation that is no longer current."""

    code = "stale_generation"

    def __init__(self, key: str, offered: int, current: int) -> None:
        self.key = key
        self.offered = offered
        self.current = current
        super().__init__(
            f"key {key!r}: offered generation {offered} but the current generation is {current}"
        )


class EpochMismatchError(LeaseError):
    code = "epoch_mismatch"

    def __init__(self, node: str, offered_epoch: int, current_epoch: int) -> None:
        self.node = node
        self.offered_epoch = offered_epoch
        self.current_epoch = current_epoch
        super().__init__(
            f"node {node!r}: offered epoch {offered_epoch} but membership epoch is {current_epoch}"
        )


class QuorumError(AtlasError):
    code = "quorum_error"


class QuorumShortfallError(QuorumError):
    """Fewer replicas counted toward a quorum than the configuration requires.

    The count is of *votes*, which is not the same as the count of replicas
    that hold the data. The epoch is in the message because a shortfall is
    always read against the membership it happened under.
    """

    code = "quorum_shortfall"

    def __init__(self, key: str, epoch: int, counted: int, needed: int, *, phase: str = "write", failures=()) -> None:
        self.key = key
        self.epoch = epoch
        self.counted = counted
        self.needed = needed
        self.phase = phase
        self.failures = tuple(failures)
        detail = f"; failures: {list(self.failures)}" if self.failures else ""
        super().__init__(
            f"acks below quorum for epoch {epoch}: {phase} of {key!r} counted {counted} of {needed}{detail}"
        )


class ConvergenceError(AtlasError):
    """Anti-entropy finished its pass and a replica the plan names still disagrees."""

    code = "convergence_error"

    def __init__(self, shard: int, epoch: int, keys) -> None:
        self.shard = shard
        self.epoch = epoch
        self.keys = tuple(keys)
        super().__init__(
            f"shard {shard} did not converge for epoch {epoch}: {list(self.keys)} still differ between replicas the plan names"
        )


class ReadRepairConflictError(AtlasError):
    """Two replicas disagree and repair could not choose a winner."""

    code = "read_repair_conflict"

    def __init__(self, key: str, left: object, right: object) -> None:
        self.key = key
        self.left = left
        self.right = right
        super().__init__(
            f"read repair for {key!r}: replicas disagree and neither vector is a superset "
            f"(left={left!r}, right={right!r})"
        )


class WALIntegrityError(AtlasError):
    code = "wal_integrity"


class TornFrameError(WALIntegrityError):
    code = "torn_frame"


class ChecksumMismatchError(WALIntegrityError):
    code = "checksum_mismatch"


class SnapshotError(AtlasError):
    code = "snapshot_error"


class ReplayError(AtlasError):
    code = "replay_error"


class MigrationError(AtlasError):
    code = "migration_error"


class DuplicateKeyError(AtlasError):
    code = "duplicate_key"

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"duplicate key: {key!r}")
