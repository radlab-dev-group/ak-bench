"""Atlas: a sharded, replicated, fenced key-value store.

The public surface is intentionally small. Everything an agent needs for the
normal path is reachable from here; the subsystems are importable but their
contracts are documented in :mod:`SPEC.md` rather than in this module.
"""

from .errors import (
    AtlasError,
    ChecksumMismatchError,
    ConfigError,
    DuplicateKeyError,
    EpochMismatchError,
    KeyNotFoundError,
    LeaseError,
    MigrationError,
    QuorumError,
    ReadRepairConflictError,
    ReplayError,
    SnapshotError,
    StaleGenerationError,
    TornFrameError,
    WALIntegrityError,
)
from .store import Atlas, AtlasBuilder
from .values import Record

__all__ = [
    "Atlas",
    "AtlasBuilder",
    "Record",
    "AtlasError",
    "ChecksumMismatchError",
    "ConfigError",
    "DuplicateKeyError",
    "EpochMismatchError",
    "KeyNotFoundError",
    "LeaseError",
    "MigrationError",
    "QuorumError",
    "ReadRepairConflictError",
    "ReplayError",
    "SnapshotError",
    "StaleGenerationError",
    "TornFrameError",
    "WALIntegrityError",
]

__version__ = "3.0.0"
