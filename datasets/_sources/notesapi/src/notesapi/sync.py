"""Merging a client's notes into the server's copy. The rules are the task.

``merge(server, client)`` returns a :class:`MergeResult` describing what the
server should hold after the client copy is applied. Both arguments map a note
id to a :class:`~notesapi.store.Note`; neither mapping is modified.

Timestamps
    Every note carries ``updated_at``, a unix second, and the higher one wins
    the right to be remembered. A tombstone (``deleted_at`` set) is a write like
    any other: it wins by its own ``updated_at``, not by being a deletion.

The rules, in order
    1. An id only the client has is an ``insert``, and the client note wins.
    2. An id both have, where the client's ``updated_at`` is **strictly** newer,
       is won by the client note: it is a ``delete`` when that note is a
       tombstone, an ``update`` otherwise.
    3. An id both have where the client's ``updated_at`` is older is won by the
       server note. Nothing is listed: an out-of-date client is not an event.
    4. An id both have with the **same** ``updated_at`` is ``unchanged`` when
       the two notes agree on body, on tags and on being deleted or not;
       otherwise it is a ``conflict``, because the merge does not guess which
       side is right.
    5. An id only the server has is kept as it is. The client copy is not a list
       of everything that exists, so an id missing from it is never a deletion.

What the server ends up holding
    ``wins`` carries an entry for **every** id either side had: the client note
    where the client won rules 1 and 2, the server note everywhere else —
    including every ``conflict``, where the server keeps what it already had.

The result
    :class:`MergeResult` exposes ``wins`` (a ``dict`` of id to note) and the
    lists ``inserts``, ``updates``, ``deletes``, ``unchanged`` and
    ``conflicts``, each a sorted list of ids. No id appears in two of the
    lists, and an id appears in no list at all exactly when the server kept its
    own note without the client having changed anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from notesapi.store import Note


@dataclass
class MergeResult:
    """What the merge decided; every list holds note ids and is sorted."""

    wins: dict[str, Note] = field(default_factory=dict)
    inserts: list[str] = field(default_factory=list)
    updates: list[str] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    LISTS: ClassVar[tuple[str, ...]] = (
        "inserts",
        "updates",
        "deletes",
        "unchanged",
        "conflicts",
    )

    def listed(self, note_id: str) -> bool:
        """Whether the id was placed in one of the five lists."""
        return any(note_id in getattr(self, name) for name in self.LISTS)


def merge(server: dict[str, Note], client: dict[str, Note]) -> MergeResult:
    """Merge a client copy into a server copy under the rules in this module."""
    raise NotImplementedError("merge is specified in this module and not yet written")
