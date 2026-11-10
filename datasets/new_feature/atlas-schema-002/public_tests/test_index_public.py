"""Visible checks for index evolution. A subset, not the whole evidence."""

import pytest

from atlas import evolution, tables
from atlas.errors import DuplicateKeyError
from atlas.values import Record
from atlas.vclock import VersionVector


def record(key, *, generation=1, lsn=0, writer="w", deleted=False):
    return Record(
        key=key,
        value=None if deleted else {"k": key},
        generation=generation,
        vector=VersionVector.new({writer: generation}),
        deleted=deleted,
        lsn=lsn,
        written_at=0,
        writer=writer,
    )


def test_the_schema_declares_an_index_by_generation():
    name, columns, unique, where = tables.index("by_generation")
    assert columns == ("generation", "key")
    assert unique is False and where == ""


def test_entries_are_the_index_columns_then_the_key_in_order():
    rows = [record("b", generation=2, lsn=2), record("a", generation=1, lsn=1), record("c", generation=2, lsn=3)]
    assert evolution.project_index("by_generation", rows) == ((1, "a"), (2, "b"), (2, "c"))
    assert evolution.project_index("by_writer", rows) == (("w", "a"), ("w", "b"), ("w", "c"))


def test_a_partial_index_skips_tombstones_and_a_unique_index_refuses_a_repeat():
    rows = [record("a", lsn=1), record("b", lsn=2, deleted=True), record("c", lsn=1)]
    assert evolution.project_index("live_only", rows) == ((False, "a"), (False, "c"))
    with pytest.raises(DuplicateKeyError):
        evolution.project_index("by_lsn", rows)
