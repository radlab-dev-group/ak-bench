"""Visible checks for schema evolution. A subset, not the whole evidence."""

import pytest

from atlas import evolution
from atlas.registry import StrategySet
from atlas.storage import ShardStorage
from atlas.values import Record


def test_a_legacy_v1_row_is_read_as_a_current_record():
    payload = {"key": "k", "value": '{"a":1}', "gen": 2, "lsn": 7}
    assert evolution.detect_version(payload) == 1
    record = evolution.decode_row(payload)
    assert record.value == {"a": 1}
    assert record.generation == 2 and record.lsn == 7
    assert record.writer == evolution.LEGACY_WRITER
    assert not record.deleted


def test_a_null_value_in_a_legacy_row_is_a_tombstone():
    record = evolution.decode_row({"key": "k", "value": None, "gen": 3, "lsn": 8})
    assert record.deleted


def test_a_current_row_downgrades_to_the_six_column_layout():
    record = Record.put("k", {"b": 1}, writer="n1", lsn=4, written_at=1700000000000)
    v2 = evolution.encode_row(record, version=2)
    assert set(v2) == {"key", "value", "gen", "lsn", "at", "writer"}
    assert v2["value"] == {"b": 1} and v2["writer"] == "n1"
    v1 = evolution.encode_row(record, version=1)
    assert set(v1) == {"key", "value", "gen", "lsn"}
    assert isinstance(v1["value"], str)


def test_a_window_dual_writes_for_a_pinned_reader(tmp_path):
    storage = ShardStorage(tmp_path / "shard", 0)
    storage.put("plain", 1)
    window = evolution.MigrationWindow(storage, pinned=1)
    window.put("shadowed", 2)
    visible = evolution.PinnedReader(1).visible_rows(storage.log)
    assert "shadowed" in visible
    assert "plain" not in visible


def test_the_upgraders_are_registered_once():
    strategies = StrategySet()
    evolution.install_upgraders(strategies)
    evolution.install_upgraders(strategies)
    assert "records:v1->v2" in strategies.evolution.names()
