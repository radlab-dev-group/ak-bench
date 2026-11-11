"""The symptom a developer can reproduce: a tie goes to the local copy."""

from __future__ import annotations

from syncer import Version, resolve


def test_a_timestamp_tie_goes_to_the_remote_version():
    local = Version("local", 10, "local")
    remote = Version("remote", 10, "remote")
    assert resolve(local, remote) is remote


def test_a_newer_local_version_still_wins():
    local = Version("new", 20, "local")
    remote = Version("old", 10, "remote")
    assert resolve(local, remote) is local
