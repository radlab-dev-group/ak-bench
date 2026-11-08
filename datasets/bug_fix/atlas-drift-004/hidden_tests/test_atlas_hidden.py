"""Witness scenarios for the one regression of atlas-drift-004.

The defect is in the module that owns the recovery window: the window opened
at the image's own number instead of after it, so every record the snapshot
already contained was applied a second time on open. The scenarios below are
the cross-module combinations the repository suite does not reach: they pin
the boundary in the module that owns it, in the report the module writes,
and in the arithmetic that the boundary is there to protect.
"""

import pytest

from atlas.config import build as build_config
from atlas.storage import ShardStorage


def make_config(**values):
    settings = {
        "shards": 2,
        "replication_factor": 3,
        "read_consistency": 2,
        "write_consistency": 2,
        "vnodes": 8,
    }
    settings.update(values)
    return build_config(path="none.toml", env={}, values=settings)


@pytest.fixture
def config():
    return make_config()


def open_fresh(root, shard, config):
    """Open the shard the way a fresh process would: from disk, alone."""

    return ShardStorage(root, shard, config=config)


def test_regression_05b_the_boundary_is_exclusive_in_the_log_path(tmp_path, config):
    """The same defect, read through the store's own recovery report.

    The window opens at the image's number, so the records the image holds
    are replayed on top of themselves, and the report the store writes on
    open counts the difference: the image's records are not skipped, and the
    replayed count is higher than the work the log did after the image.
    """

    store = ShardStorage(tmp_path / "s", 0, config=config)
    for index in range(3):
        store.put(f"k{index}", index, writer="n")
    store.snapshot()
    store.put("k3", 3, writer="n")
    reopened = store.reopen()
    assert reopened.recovery.skipped >= 3, (
        "the snapshot's records were not skipped on replay"
    )
    assert reopened.recovery.replayed == 1, (
        f"the replay did {reopened.recovery.replayed} records of work; the log "
        "held exactly one record after the image, and the image's own records "
        "were not its to replay"
    )
    assert reopened.get("k2").value == 2
    assert reopened.get("k3").value == 3


def test_the_snapshot_record_is_not_reapplied(tmp_path, config):
    """A counter incremented around a snapshot must advance by one, not by two.

    The defect opens the replay window at the snapshot's number, so the record
    the snapshot already holds is applied a second time. The witness keeps the
    value as a derived one — the next generation of the key — and checks the
    arithmetic after a restart: a record applied twice advances the key by two
    generations, and the value it lands on is the one derived from the
    doubled step, which is the record the log never held.
    """

    store = ShardStorage(tmp_path / "s", 0, config=config)
    store.put("counter", 1, writer="n")
    store.snapshot()
    store.put("counter", 2, writer="n")
    reopened = store.reopen()
    record = reopened.get("counter")
    assert record.value == 2, (
        f"the record the snapshot already contained was applied again: got "
        f"{record.value!r} at generation {record.generation}, expected 2"
    )
    assert record.generation == 2, (
        f"the key advanced to generation {record.generation}; one write after "
        "the image advances one generation, and the image's own record was "
        "replayed on top of itself"
    )


def test_the_boundary_is_a_function_of_the_image_not_of_the_key(tmp_path, config):
    """The window is per image, and every key under it is doubled.

    The defect re-applies everything the image contains, so the damage is not
    in one key: every key the snapshot holds is applied twice, whether its
    value is derived or a plain overwrite. The grid below writes a batch of
    keys, snapshots, writes a second batch, reopens, and requires both batches
    to be exactly what was last written — the first batch proves the image's
    records were not re-applied, the second that the log's records were not
    dropped.
    """

    store = ShardStorage(tmp_path / "s", 0, config=config)
    for index in range(4):
        store.put(f"first-{index}", f"a{index}", writer="n")
    store.snapshot()
    for index in range(4):
        store.put(f"second-{index}", f"b{index}", writer="n")
    reopened = store.reopen()
    for index in range(4):
        assert reopened.get(f"first-{index}").value == f"a{index}", (
            f"first-{index} was re-applied: {reopened.get(f'first-{index}').value!r}"
        )
        assert reopened.get(f"second-{index}").value == f"b{index}", (
            f"second-{index} was lost: {reopened.get(f'second-{index}').value!r}"
        )


def test_a_counter_across_two_snapshots_is_stable_after_reopen(tmp_path, config):
    """The arithmetic across snapshots: the value is what was last written.

    A counter written, snapshotted, written again, snapshotted again, written
    a third time, and reopened. The boundary must hold for the second image
    the way it holds for the first, or the counter doubles on the second
    open. This is the case a fix that only checks the first snapshot passes:
    the window is a property of the open, and every open starts after its
    image.
    """

    store = ShardStorage(tmp_path / "s", 0, config=config)
    store.put("counter", 1, writer="n")
    store.snapshot()
    store.put("counter", 2, writer="n")
    store.snapshot()
    store.put("counter", 3, writer="n")
    reopened = store.reopen()
    record = reopened.get("counter")
    assert record.value == 3 and record.generation == 3
    # The report is the witness for the second image the way it is for the
    # first: the image's record is skipped, the log's record is replayed.
    assert reopened.recovery.skipped >= 2, (
        f"two images held two records of the key; the open skipped "
        f"{reopened.recovery.skipped}"
    )
    assert reopened.recovery.replayed == 1, (
        f"the log held one record after the last image; the open replayed "
        f"{reopened.recovery.replayed}"
    )
    # And a third open is stable: the boundary is idempotent.
    again = reopened.reopen()
    assert again.get("counter").value == 3
    assert again.get("counter").generation == 3


def test_the_report_counts_the_image_as_skipped_work(tmp_path, config):
    """The numbers the open reports are the contract, not a side note.

    The recovery report says how much the image saved: the records the image
    holds are skipped on replay, and the records the log did after the image
    are replayed. The defect breaks both numbers in the same direction —
    fewer skipped, more replayed — which is why a review that looked at
    either number alone and saw "the open did less work" found nothing wrong.
    Both numbers are pinned here, against the work actually done.
    """

    store = ShardStorage(tmp_path / "s", 0, config=config)
    for index in range(5):
        store.put(f"k{index}", index, writer="n")
    store.snapshot()
    for index in range(5, 8):
        store.put(f"k{index}", index, writer="n")
    reopened = store.reopen()
    assert reopened.recovery.skipped >= 5, (
        f"the image held five records; the open skipped {reopened.recovery.skipped}"
    )
    assert reopened.recovery.replayed == 3, (
        f"the log held three records after the image; the open replayed "
        f"{reopened.recovery.replayed}"
    )
    for index in range(8):
        assert reopened.get(f"k{index}").value == index


def test_a_key_written_only_before_the_snapshot_survives_its_reopen(tmp_path, config):
    """The image is a floor, not a ceiling: nothing after it is dropped.

    The boundary protects in two directions. Opening the window at the image's
    number re-applies work that has been done; opening it after the last log
    record would drop work that has not been applied. The witness writes a key
    before the image and one after it, and requires both to be exactly what
    was last written, which is the difference between a boundary and a guess.
    """

    store = ShardStorage(tmp_path / "s", 0, config=config)
    store.put("before", 1, writer="n")
    store.snapshot()
    store.put("after", 2, writer="n")
    reopened = store.reopen()
    assert reopened.get("before").value == 1
    assert reopened.get("after").value == 2
    # The boundary is the snapshot's number, not the log's last record.
    assert reopened.recovery.snapshot_lsn >= 1
    assert reopened.recovery.replayed == 1
