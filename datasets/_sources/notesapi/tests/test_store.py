"""The part of the fixture that is finished: the note store."""

import pytest

from notesapi.errors import UnknownNote
from notesapi.store import Note, NoteStore


def test_a_note_is_live_until_it_is_deleted():
    note = Note(note_id="n1", body="hello", updated_at=10)
    assert not note.deleted


def test_a_tombstone_records_the_second_it_was_deleted_at():
    store = NoteStore()
    store.put(Note(note_id="n1", body="hello", updated_at=10))
    deleted = store.delete("n1", at=20)
    assert deleted.deleted
    assert deleted.deleted_at == 20


def test_a_deleted_note_is_not_live_but_keeps_its_id():
    store = NoteStore()
    store.put(Note(note_id="n1", body="hello", updated_at=10))
    store.delete("n1", at=20)
    assert [note.note_id for note in store.live()] == []
    assert [note.note_id for note in store.tombstones()] == ["n1"]
    assert store.ids() == ["n1"]


def test_writing_an_older_version_is_refused():
    store = NoteStore()
    store.put(Note(note_id="n1", body="new", updated_at=30))
    with pytest.raises(ValueError):
        store.put(Note(note_id="n1", body="old", updated_at=20))


def test_an_unknown_id_is_reported():
    with pytest.raises(UnknownNote):
        NoteStore().get("nope")


def test_a_tombstone_may_be_written_again():
    store = NoteStore()
    store.put(Note(note_id="n1", body="hello", updated_at=10))
    store.delete("n1", at=20)
    again = store.delete("n1", at=30)
    assert again.deleted_at == 20  # already a tombstone: the call is a no-op


def test_a_note_needs_an_id():
    with pytest.raises(ValueError):
        Note(note_id="", body="x")


def test_a_tombstone_cannot_predate_its_note():
    with pytest.raises(ValueError):
        Note(note_id="n1", body="x", updated_at=30, deleted_at=20)
