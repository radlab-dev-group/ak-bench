"""Finding notes. The rules are in this docstring; the implementation is the task.

``search_notes(store, query, *, tags=None, limit=None, offset=0)`` returns a
list of notes, best match first.

Matching
    A query is split on whitespace into terms. A note matches when **every**
    term occurs in the note's body or in one of its tags, comparing
    case-insensitively. A term matches a substring, not a whole word: the term
    ``report`` matches ``reporting``. An empty query (empty string, or only
    whitespace) matches every live note.

Ranking
    A note scores one point for every term it contains in the body, and two
    points for every term it contains in a tag. Notes are ordered by score
    descending, then by ``updated_at`` descending (newest first), then by
    ``note_id`` ascending. The order is total: no two notes tie.

Filtering and paging
    Deleted notes never match. When ``tags`` is given, a note must carry every
    one of them (case-insensitively) to be considered at all. ``offset`` skips
    that many matching notes, and ``limit`` caps how many are returned; a
    ``limit`` of ``None`` means no cap. Negative ``offset`` or a negative
    ``limit`` raise :class:`ValueError`.

The function returns the notes themselves, not their ids, and it does not
modify the store.
"""

from __future__ import annotations

from collections.abc import Iterable

from notesapi.store import Note, NoteStore


def search_notes(
    store: NoteStore,
    query: str,
    *,
    tags: Iterable[str] | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[Note]:
    """Return the notes matching ``query`` under the rules in this module."""
    raise NotImplementedError("search_notes is specified in this module and not yet written")
