"""A small note-taking service: store, search, sync.

Notes are identified by a stable id. Every note carries an ``updated_at`` in
unix seconds and a list of tags. A note that was deleted on the client side is
kept as a tombstone so the deletion can be merged back into the server.
"""

from notesapi.errors import Conflict, UnknownNote
from notesapi.search import search_notes
from notesapi.store import Note, NoteStore
from notesapi.sync import merge

__all__ = [
    "Conflict",
    "Note",
    "NoteStore",
    "UnknownNote",
    "merge",
    "search_notes",
]
