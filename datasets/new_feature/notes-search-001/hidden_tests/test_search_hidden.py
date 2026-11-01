"""The specification, tested rule by rule.

Every assertion here is a sentence from the docstring of ``search_notes``.
"""

import pytest

from notesapi.search import search_notes
from notesapi.store import Note, NoteStore


def store_with(*notes):
    store = NoteStore()
    for note in notes:
        store.put(note)
    return store


def test_every_term_must_occur():
    store = store_with(
        Note(note_id="both", body="alpha beta", updated_at=1),
        Note(note_id="one", body="alpha", updated_at=2),
    )
    assert [n.note_id for n in search_notes(store, "alpha beta")] == ["both"]


def test_a_term_matches_a_substring_not_a_whole_word():
    store = store_with(Note(note_id="a", body="reporting year", updated_at=1))
    assert [n.note_id for n in search_notes(store, "report")] == ["a"]
    assert [n.note_id for n in search_notes(store, "port")] == ["a"]


def test_a_term_may_be_satisfied_by_a_tag():
    store = store_with(Note(note_id="a", body="nothing", tags=("invoice",), updated_at=1))
    assert [n.note_id for n in search_notes(store, "invoice")] == ["a"]


def test_a_blank_query_matches_every_live_note_newest_first():
    """A blank query scores nothing, so the second ordering rule decides it."""
    store = store_with(
        Note(note_id="b", body="x", updated_at=2),
        Note(note_id="a", body="y", updated_at=1),
    )
    assert [n.note_id for n in search_notes(store, "")] == ["b", "a"]
    assert [n.note_id for n in search_notes(store, "  \t ")] == ["b", "a"]


def test_scoring_is_one_for_a_body_hit_and_two_for_a_tag_hit():
    store = store_with(
        Note(note_id="body", body="alpha beta", updated_at=9),
        Note(note_id="tag", body="nothing", tags=("alpha",), updated_at=9),
    )
    assert [n.note_id for n in search_notes(store, "alpha")] == ["tag", "body"]


def test_two_tag_hits_beat_one_tag_hit():
    """Both notes match both terms; the one with the terms in tags ranks first."""
    store = store_with(
        # alpha in a tag (2) and beta in the body (1): 3
        Note(note_id="one-tag", body="beta", tags=("alpha",), updated_at=5),
        # alpha and beta both in tags (2 + 2): 4
        Note(note_id="two-tags", body="x", tags=("alpha", "beta"), updated_at=5),
    )
    assert [n.note_id for n in search_notes(store, "alpha beta")] == ["two-tags", "one-tag"]


def test_ties_in_score_break_on_newest_first():
    store = store_with(
        Note(note_id="older", body="alpha", updated_at=10),
        Note(note_id="newer", body="alpha", updated_at=20),
    )
    assert [n.note_id for n in search_notes(store, "alpha")] == ["newer", "older"]


def test_a_full_tie_breaks_on_the_note_id():
    store = store_with(
        Note(note_id="b", body="alpha", updated_at=10),
        Note(note_id="a", body="alpha", updated_at=10),
    )
    assert [n.note_id for n in search_notes(store, "alpha")] == ["a", "b"]


def test_the_order_is_total_across_every_criterion():
    store = store_with(
        Note(note_id="z", body="alpha", tags=("alpha",), updated_at=1),
        Note(note_id="m", body="alpha", updated_at=99),
        Note(note_id="n", body="alpha", updated_at=99),
    )
    assert [n.note_id for n in search_notes(store, "alpha")] == ["z", "m", "n"]


def test_deleted_notes_never_match_even_with_a_blank_query():
    store = store_with(
        Note(note_id="live", body="alpha", updated_at=1),
        Note(note_id="dead", body="alpha", updated_at=2),
    )
    store.delete("dead", at=5)
    assert [n.note_id for n in search_notes(store, "")] == ["live"]
    assert [n.note_id for n in search_notes(store, "alpha")] == ["live"]


def test_the_tag_filter_requires_every_tag():
    store = store_with(
        Note(note_id="both", body="x", tags=("work", "urgent"), updated_at=2),
        Note(note_id="one", body="x", tags=("work",), updated_at=9),
    )
    assert [n.note_id for n in search_notes(store, "x", tags=["work", "urgent"])] == ["both"]


def test_the_tag_filter_ignores_case():
    store = store_with(Note(note_id="a", body="x", tags=("Work",), updated_at=1))
    assert [n.note_id for n in search_notes(store, "x", tags=["work"])] == ["a"]


def test_the_tag_filter_alone_still_returns_bodies_it_has():
    store = store_with(
        Note(note_id="a", body="hold", tags=("hold",), updated_at=1),
        Note(note_id="b", body="other", tags=("x",), updated_at=2),
    )
    assert [n.note_id for n in search_notes(store, "", tags=["hold"])] == ["a"]


def test_offset_skips_and_limit_caps():
    store = store_with(
        Note(note_id="a", body="alpha", updated_at=3),
        Note(note_id="b", body="alpha", updated_at=2),
        Note(note_id="c", body="alpha", updated_at=1),
    )
    assert [n.note_id for n in search_notes(store, "alpha", limit=2)] == ["a", "b"]
    assert [n.note_id for n in search_notes(store, "alpha", offset=2)] == ["c"]
    assert [n.note_id for n in search_notes(store, "alpha", offset=1, limit=1)] == ["b"]
    assert search_notes(store, "alpha", offset=99) == []


def test_a_limit_of_none_means_no_cap():
    store = store_with(
        Note(note_id="a", body="alpha", updated_at=1),
        Note(note_id="b", body="alpha", updated_at=2),
    )
    assert len(search_notes(store, "alpha", limit=None)) == 2


def test_negative_paging_arguments_are_refused():
    store = store_with(Note(note_id="a", body="alpha", updated_at=1))
    with pytest.raises(ValueError):
        search_notes(store, "alpha", offset=-1)
    with pytest.raises(ValueError):
        search_notes(store, "alpha", limit=-1)


def test_the_store_is_not_modified():
    store = store_with(
        Note(note_id="a", body="alpha", updated_at=1),
        Note(note_id="dead", body="alpha", updated_at=2),
    )
    store.delete("dead", at=5)
    before = store.ids()
    search_notes(store, "alpha")
    assert store.ids() == before
    assert [n.deleted for n in (store.get(i) for i in before)] == [False, True]


def test_the_result_holds_notes_not_ids():
    store = store_with(Note(note_id="a", body="alpha", updated_at=1))
    (only,) = search_notes(store, "alpha")
    assert isinstance(only, Note)
    assert only.body == "alpha"


def test_no_match_returns_an_empty_list():
    store = store_with(Note(note_id="a", body="alpha", updated_at=1))
    assert search_notes(store, "gamma") == []
