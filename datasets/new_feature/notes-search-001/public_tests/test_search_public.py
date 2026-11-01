"""The examples a developer is given: the shape of the contract, not its edges."""

from notesapi.search import search_notes
from notesapi.store import Note, NoteStore


def store_with(*notes):
    store = NoteStore()
    for note in notes:
        store.put(note)
    return store


def test_a_blank_query_returns_every_live_note_newest_first():
    store = store_with(
        Note(note_id="b", body="second", updated_at=2),
        Note(note_id="a", body="first", updated_at=1),
    )
    assert [n.note_id for n in search_notes(store, "")] == ["b", "a"]
    assert [n.note_id for n in search_notes(store, "   ")] == ["b", "a"]


def test_a_term_matches_case_insensitively():
    store = store_with(Note(note_id="a", body="Report", updated_at=1))
    assert [n.note_id for n in search_notes(store, "REPORT")] == ["a"]


def test_a_tag_hit_outranks_a_body_hit():
    store = store_with(
        Note(note_id="body-only", body="quarterly report", updated_at=9),
        Note(note_id="tag-hit", body="nothing", tags=("report",), updated_at=1),
    )
    assert [n.note_id for n in search_notes(store, "report")] == ["tag-hit", "body-only"]


def test_deleted_notes_are_never_returned():
    store = store_with(Note(note_id="a", body="alpha", updated_at=1))
    store.delete("a", at=5)
    assert search_notes(store, "alpha") == []
