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

def __getattr__(name):
    # The store pulls in the whole storage stack; resolving it lazily keeps the
    # leaf modules importable on their own.
    if name in ("Atlas", "AtlasBuilder"):
        from . import store

        return getattr(store, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
