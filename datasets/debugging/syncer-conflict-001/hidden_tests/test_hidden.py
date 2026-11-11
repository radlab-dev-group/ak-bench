"""The failing scenario, proven from every side.

These tests fail on the base commit (the defect is in the base code) and
pass once the tie-break is repaired.
"""

from __future__ import annotations

from syncer import Version, resolve


def test_a_timestamp_tie_goes_to_the_remote_version():
    local = Version("local", 10, "local")
    remote = Version("remote", 10, "remote")
    assert resolve(local, remote) is remote


def test_a_tie_at_zero_goes_to_the_remote_version():
    local = Version("local", 0, "local")
    remote = Version("remote", 0, "remote")
    assert resolve(local, remote) is remote


def test_a_newer_local_version_still_wins():
    local = Version("new", 20, "local")
    remote = Version("old", 10, "remote")
    assert resolve(local, remote) is local


def test_a_newer_remote_version_still_wins():
    local = Version("old", 10, "local")
    remote = Version("new", 20, "remote")
    assert resolve(local, remote) is remote


def test_a_one_second_difference_is_not_a_tie():
    local = Version("local", 11, "local")
    remote = Version("remote", 10, "remote")
    assert resolve(local, remote) is local


def test_the_winner_is_the_version_object_itself():
    local = Version("local", 10, "local")
    remote = Version("remote", 10, "remote")
    winner = resolve(local, remote)
    assert winner is remote
    assert winner.content == "remote"
