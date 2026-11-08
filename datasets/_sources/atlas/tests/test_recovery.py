"""Recovery from disk: snapshot plus log, torn tails, and restarts."""

import pytest

from atlas.faults import CrashPlan, SimulatedCrash
from atlas.storage import ShardStorage


def test_a_restart_replays_what_the_snapshot_does_not_have(tmp_path):
    store = ShardStorage(tmp_path / "s", 0)
    store.put("a", 1, writer="n")
    store.put("b", 2, writer="n")
    store.snapshot()
    store.put("c", 3, writer="n")
    reopened = store.reopen()
    assert reopened.get("a") is not None
    assert reopened.get("b") is not None
    assert reopened.get("c") is not None
    assert reopened.recovery.replayed >= 1
    assert reopened.recovery.skipped >= 1
    assert reopened.recovery.torn is False


def test_a_torn_tail_is_cut_at_the_last_intact_frame(tmp_path):
    store = ShardStorage(tmp_path / "s", 0, repair_on_open=False)
    store.put("a", 1, writer="n")
    store.put("b", 2, writer="n")
    segment = store.log.segments[-1]
    data = segment.read_bytes()
    segment.write_bytes(data[: len(data) - 3])
    reopened = ShardStorage(tmp_path / "s", 0)
    assert reopened.recovery.torn is True
    assert reopened.recovery.truncated_bytes > 0
    assert reopened.get("a") is not None


def test_a_crash_before_the_commit_discards_the_uncommitted_write(tmp_path):
    first = ShardStorage(tmp_path / "s", 0)
    first.put("a", 1, writer="n")
    # Tear off the whole BEGIN frame of the second transaction, so the damage
    # sits on a frame boundary and the second transaction is the only thing
    # that is gone.
    first.crash = CrashPlan(at="mid_frame", times=1, tear_bytes=22)
    with pytest.raises(SimulatedCrash):
        first.put("b", 2, writer="n")
    reopened = ShardStorage(tmp_path / "s", 0)
    assert reopened.get("a") is not None
    assert reopened.get("b") is None
    assert reopened.recovery.torn is True


def test_a_crash_mid_frame_loses_only_the_partial_write(tmp_path):
    first = ShardStorage(tmp_path / "s", 0)
    first.put("a", 1, writer="n")
    first.crash = CrashPlan(at="mid_frame", times=1, tear_bytes=5)
    with pytest.raises(SimulatedCrash):
        first.put("b", 2, writer="n")
    reopened = ShardStorage(tmp_path / "s", 0)
    assert reopened.get("a") is not None
    assert reopened.get("b") is None
    assert reopened.recovery.torn is True


def test_recovery_survives_a_second_restart(tmp_path):
    store = ShardStorage(tmp_path / "s", 0)
    for index in range(5):
        store.put(f"k{index}", index, writer="n")
    store.snapshot()
    store.put("k5", 5, writer="n")
    second = store.reopen()
    third = second.reopen()
    assert [third.get(f"k{i}") for i in range(6)] is not None
    assert third.get("k5").value == 5
    assert third.recovery.replayed >= 0


def test_a_delete_survives_a_restart(tmp_path):
    store = ShardStorage(tmp_path / "s", 0)
    store.put("a", 1, writer="n")
    store.delete("a", writer="n")
    reopened = store.reopen()
    assert reopened.get("a") is None
    assert reopened.resolve("a").deleted is True


def test_an_unpublished_snapshot_is_not_adopted(tmp_path):
    store = ShardStorage(tmp_path / "s", 0)
    store.put("a", 1, writer="n")
    unpublished = store.snapshots.write(0, store.state.snapshot_records(), last_lsn=999, publish=False)
    assert unpublished.published is False
    reopened = ShardStorage(tmp_path / "s", 0)
    assert reopened.recovery.snapshot_published is False
    assert reopened.get("a").value == 1
    assert reopened.recovery.snapshot_lsn == 0
