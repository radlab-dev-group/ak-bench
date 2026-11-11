"""The finished part of the fixture: clear winners.

The suite deliberately never ties on the timestamp, so a defect in the
tie-break is invisible here.
"""

from __future__ import annotations

from syncer import Version, resolve


def test_the_newer_local_version_wins():
    local = Version("new", 20, "local")
    remote = Version("old", 10, "remote")
    assert resolve(local, remote) is local


def test_the_newer_remote_version_wins():
    local = Version("old", 10, "local")
    remote = Version("new", 20, "remote")
    assert resolve(local, remote) is remote
