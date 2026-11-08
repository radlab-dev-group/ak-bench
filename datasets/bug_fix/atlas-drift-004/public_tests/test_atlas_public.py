"""Visible checks for the exclusive boundary. These are not the whole evidence.

They fail on a store that has lost the rule and pass on a correct one, and
they are deliberately less surgical than the hidden scenarios: they say which
rule broke, not which line broke it.
"""

from atlas.storage import ShardStorage


def test_a_snapshot_record_is_not_reapplied(tmp_path):
    store = ShardStorage(tmp_path / "s", 0)
    store.put("counter", 1, writer="n")
    store.snapshot()
    store.put("counter", 2, writer="n")
    reopened = store.reopen()
    assert reopened.get("counter").value == 2


def test_the_snapshot_records_are_skipped_on_replay(tmp_path):
    store = ShardStorage(tmp_path / "s", 0)
    for index in range(3):
        store.put(f"k{index}", index, writer="n")
    store.snapshot()
    store.put("after", 1, writer="n")
    reopened = store.reopen()
    assert reopened.recovery.skipped >= 3
    assert reopened.get("after").value == 1
