"""Notes in memory, with the deletion tombstone a merge needs.

A note is a record with an id, a body, a set of tags and the unix second it was
last written in. A deleted note is not dropped: it stays as a tombstone with
``deleted_at`` set, so that a synchronisation can tell "this was deleted" apart
from "this never existed".
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from notesapi.errors import UnknownNote


@dataclass(frozen=True)
class Note:
    """One note. ``updated_at`` is a unix second and is monotonic per id."""

    note_id: str
    body: str
    tags: tuple[str, ...] = ()
    updated_at: int = 0
    deleted_at: int | None = None

    def __post_init__(self) -> None:
        if not self.note_id:
            raise ValueError("a note needs an id")
        if self.updated_at < 0:
            raise ValueError(f"updated_at cannot be negative, got {self.updated_at}")
        if self.deleted_at is not None and self.deleted_at < self.updated_at:
            raise ValueError("a tombstone cannot predate the note it deletes")

    @property
    def deleted(self) -> bool:
        return self.deleted_at is not None


@dataclass
class NoteStore:
    """A dictionary of notes that keeps tombstones instead of forgetting them."""

    _notes: dict[str, Note] = field(default_factory=dict, repr=False)

    def put(self, note: Note) -> Note:
        """Insert or replace a note, refusing to move time backwards."""
        previous = self._notes.get(note.note_id)
        if previous is not None and note.updated_at < previous.updated_at:
            raise ValueError(
                f"{note.note_id}: refusing to move updated_at backwards "
                f"({previous.updated_at} -> {note.updated_at})"
            )
        self._notes[note.note_id] = note
        return note

    def get(self, note_id: str) -> Note:
        try:
            return self._notes[note_id]
        except KeyError as exc:
            raise UnknownNote(note_id) from exc

    def live(self) -> list[Note]:
        """Every note that has not been deleted, ordered by id."""
        return [note for note in (self._notes[key] for key in sorted(self._notes)) if not note.deleted]

    def tombstones(self) -> list[Note]:
        return [note for note in (self._notes[key] for key in sorted(self._notes)) if note.deleted]

    def ids(self) -> list[str]:
        return sorted(self._notes)

    def delete(self, note_id: str, *, at: int) -> Note:
        """Turn a note into a tombstone at the given second."""
        note = self.get(note_id)
        if note.deleted:
            return note
        tombstone = replace(note, deleted_at=max(at, note.updated_at))
        self._notes[note_id] = tombstone
        return tombstone
