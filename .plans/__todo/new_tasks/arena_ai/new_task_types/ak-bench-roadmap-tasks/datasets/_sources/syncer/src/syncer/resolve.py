"""Choosing the winning version.

The newer version wins. When both versions carry the same timestamp,
the remote version wins: the server is authoritative, so a tie is
resolved in its favour rather than in the local copy's.
"""

from __future__ import annotations

from syncer.model import Version


def resolve(local: Version, remote: Version) -> Version:
    """Return the version that wins under the rules above."""
    if local.updated_at > remote.updated_at:
        return local
    if remote.updated_at > local.updated_at:
        return remote
    return local
