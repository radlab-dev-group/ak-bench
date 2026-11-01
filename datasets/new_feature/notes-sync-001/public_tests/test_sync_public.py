"""The examples a developer is given: the shape of a merge, not every branch."""

from notesapi.store import Note
from notesapi.sync import merge


def test_a_note_only_the_client_has_is_inserted():
    client = {"n1": Note(note_id="n1", body="new", updated_at=5)}
    result = merge(server={}, client=client)
    assert result.inserts == ["n1"]
    assert result.wins["n1"].body == "new"


def test_a_newer_client_note_updates_the_server():
    server = {"n1": Note(note_id="n1", body="old", updated_at=5)}
    client = {"n1": Note(note_id="n1", body="new", updated_at=6)}
    result = merge(server, client)
    assert result.updates == ["n1"]
    assert result.wins["n1"].body == "new"


def test_an_identical_note_at_the_same_second_is_unchanged():
    note = Note(note_id="n1", body="same", updated_at=5)
    result = merge({"n1": note}, {"n1": note})
    assert result.unchanged == ["n1"]
    assert not result.conflicts


def test_the_same_second_and_different_bodies_is_a_conflict():
    server = {"n1": Note(note_id="n1", body="server says", updated_at=5)}
    client = {"n1": Note(note_id="n1", body="client says", updated_at=5)}
    result = merge(server, client)
    assert result.conflicts == ["n1"]
    assert result.wins["n1"].body == "server says"
