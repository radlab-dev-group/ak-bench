"""The specification, tested rule by rule.

Every assertion here is a sentence from the docstring of ``merge``. The lists
are checked for being sorted and pairwise disjoint because the contract says so,
not because any single case would notice.
"""

import pytest

from notesapi.store import Note
from notesapi.sync import MergeResult, merge


def assert_shaped(result: MergeResult) -> MergeResult:
    """The invariants of the result object, checked after every case."""
    for name in MergeResult.LISTS:
        assert getattr(result, name) == sorted(getattr(result, name)), name
    seen: set[str] = set()
    for name in MergeResult.LISTS:
        ids = set(getattr(result, name))
        assert not (seen & ids), f"an id appears in two lists: {seen & ids}"
        seen |= ids
    return result


def test_an_id_only_the_client_has_is_an_insert():
    client = {"n1": Note(note_id="n1", body="new", updated_at=5)}
    result = assert_shaped(merge({}, client))
    assert result.inserts == ["n1"]
    assert result.wins["n1"] is client["n1"]


def test_an_id_only_the_server_has_is_kept_and_not_listed():
    server = {"n1": Note(note_id="n1", body="kept", updated_at=5)}
    result = assert_shaped(merge(server, {}))
    assert result.wins["n1"] is server["n1"]
    assert not result.listed("n1")


def test_a_strictly_newer_client_note_wins_as_an_update():
    server = {"n1": Note(note_id="n1", body="old", updated_at=5)}
    client = {"n1": Note(note_id="n1", body="new", updated_at=6)}
    result = assert_shaped(merge(server, client))
    assert result.updates == ["n1"]
    assert result.wins["n1"].body == "new"


def test_an_older_client_note_loses_and_is_not_listed():
    server = {"n1": Note(note_id="n1", body="server", updated_at=9)}
    client = {"n1": Note(note_id="n1", body="client", updated_at=8)}
    result = assert_shaped(merge(server, client))
    assert result.wins["n1"].body == "server"
    assert not result.listed("n1")


def test_a_client_tombstone_that_wins_is_recorded_as_a_delete():
    server = {"n1": Note(note_id="n1", body="was here", updated_at=5)}
    client = {"n1": Note(note_id="n1", body="was here", updated_at=7, deleted_at=7)}
    result = assert_shaped(merge(server, client))
    assert result.deletes == ["n1"]
    assert result.updates == []
    assert result.wins["n1"].deleted


def test_a_server_tombstone_newer_than_the_client_note_is_kept():
    server = {"n1": Note(note_id="n1", body="gone", updated_at=10, deleted_at=10)}
    client = {"n1": Note(note_id="n1", body="still alive", updated_at=4)}
    result = assert_shaped(merge(server, client))
    assert result.wins["n1"].deleted
    assert not result.listed("n1")


def test_a_tombstone_wins_by_its_timestamp_not_by_being_a_deletion():
    server = {"n1": Note(note_id="n1", body="alive", updated_at=10)}
    client = {"n1": Note(note_id="n1", body="alive", updated_at=5, deleted_at=5)}
    result = assert_shaped(merge(server, client))
    assert result.wins["n1"].deleted is False
    assert not result.listed("n1")


def test_the_same_second_and_the_same_content_is_unchanged():
    server = {"n1": Note(note_id="n1", body="x", tags=("a",), updated_at=5)}
    client = {"n1": Note(note_id="n1", body="x", tags=("a",), updated_at=5)}
    result = assert_shaped(merge(server, client))
    assert result.unchanged == ["n1"]


def test_the_same_second_with_different_tags_is_a_conflict():
    server = {"n1": Note(note_id="n1", body="x", tags=("a",), updated_at=5)}
    client = {"n1": Note(note_id="n1", body="x", tags=("b",), updated_at=5)}
    result = assert_shaped(merge(server, client))
    assert result.conflicts == ["n1"]
    assert result.wins["n1"].tags == ("a",)


def test_the_same_second_with_one_tombstone_is_a_conflict():
    server = {"n1": Note(note_id="n1", body="x", updated_at=5)}
    client = {"n1": Note(note_id="n1", body="x", updated_at=5, deleted_at=5)}
    result = assert_shaped(merge(server, client))
    assert result.conflicts == ["n1"]
    assert result.wins["n1"].deleted is False


def test_a_conflict_keeps_the_server_note():
    server = {"n1": Note(note_id="n1", body="server", updated_at=5)}
    client = {"n1": Note(note_id="n1", body="client", updated_at=5)}
    result = assert_shaped(merge(server, client))
    assert result.wins["n1"].body == "server"


def test_wins_holds_every_id_either_side_had():
    server = {"a": Note(note_id="a", body="a", updated_at=1),
              "b": Note(note_id="b", body="b", updated_at=2)}
    client = {"b": Note(note_id="b", body="b-new", updated_at=3),
              "c": Note(note_id="c", body="c", updated_at=1)}
    result = assert_shaped(merge(server, client))
    assert sorted(result.wins) == ["a", "b", "c"]


def test_a_merge_of_two_copies_with_several_ids_splits_into_the_right_lists():
    server = {
        "inskip": Note(note_id="inskip", body="s", updated_at=1),
        "update": Note(note_id="update", body="s", updated_at=1),
        "delete": Note(note_id="delete", body="s", updated_at=1),
        "keep": Note(note_id="keep", body="s", updated_at=9),
    }
    client = {
        "insert": Note(note_id="insert", body="c", updated_at=1),
        "update": Note(note_id="update", body="c", updated_at=2),
        "delete": Note(note_id="delete", body="s", updated_at=2, deleted_at=2),
    }
    result = assert_shaped(merge(server, client))
    assert result.inserts == ["insert"]
    assert result.updates == ["update"]
    assert result.deletes == ["delete"]
    assert result.conflicts == []
    assert not result.listed("keep")
    assert result.wins["keep"].body == "s"


def test_the_two_input_mappings_are_not_modified():
    server = {"a": Note(note_id="a", body="s", updated_at=1)}
    client = {"b": Note(note_id="b", body="c", updated_at=1)}
    merge(server, client)
    assert list(server) == ["a"]
    assert list(client) == ["b"]


def test_two_empty_copies_merge_into_an_empty_result():
    result = assert_shaped(merge({}, {}))
    assert result.wins == {}
    assert all(getattr(result, name) == [] for name in MergeResult.LISTS)


def test_an_empty_server_makes_every_client_note_an_insert():
    client = {"a": Note(note_id="a", body="x", updated_at=1),
              "b": Note(note_id="b", body="y", updated_at=2)}
    result = assert_shaped(merge({}, client))
    assert result.inserts == ["a", "b"]


def test_two_tombstones_at_the_same_second_are_unchanged():
    server = {"n1": Note(note_id="n1", body="x", updated_at=6, deleted_at=6)}
    client = {"n1": Note(note_id="n1", body="x", updated_at=6, deleted_at=6)}
    result = assert_shaped(merge(server, client))
    assert result.unchanged == ["n1"]
    assert result.deletes == []


def test_a_newer_client_tombstone_over_a_server_tombstone_is_still_a_delete():
    server = {"n1": Note(note_id="n1", body="x", updated_at=5, deleted_at=5)}
    client = {"n1": Note(note_id="n1", body="x", updated_at=8, deleted_at=8)}
    result = assert_shaped(merge(server, client))
    assert result.deletes == ["n1"]
    assert result.wins["n1"].updated_at == 8
