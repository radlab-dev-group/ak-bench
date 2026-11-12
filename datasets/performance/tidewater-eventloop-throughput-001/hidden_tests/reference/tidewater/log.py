"""The replicated log: entries, the matching rule, and conflict handling.

A :class:`RaftLog` is a dense sequence of :class:`Entry` starting at
``base_index + 1``. In the seed ``base_index`` is always zero; a compacted
log (``SPEC.md`` section 6, declared) will set it to ``last_included_index``
and remember ``last_included_term`` so that ``term_at(base_index)`` still
answers. Nothing in this module assumes ``base_index == 0``; the follower's
matching check for a prefix that was compacted away is the one place that
consults the snapshot term.

Three rules live here and nowhere else:

* **log matching** (:meth:`RaftLog.matches`): a follower accepts
  ``AppendEntries`` only if it holds an entry at ``prev_log_index`` with
  term ``prev_log_term`` — index 0 with term 0 is the empty prefix, and
  always matches;
* **truncate only on conflict** (:meth:`RaftLog.append_from_leader`): a
  follower that already holds entries past ``prev_log_index`` keeps them
  unless one of them has a different term from the leader's entry at the
  same index. ``docs/adr/ADR-0005`` explains why "truncate everything after
  prev and copy" loses committed entries under reordering;
* **up-to-date** (:meth:`RaftLog.is_up_to_date`): the election restriction —
  a candidate's log is at least as up to date as the voter's if its last term
  is higher, or the terms are equal and its last index is at least as large.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .errors import StorageError
from .statemachine import Command, command_from_dict

ENTRY_NOOP = "noop"
ENTRY_COMMAND = "command"
ENTRY_CONFIG = "config"

ENTRY_KINDS = (ENTRY_NOOP, ENTRY_COMMAND, ENTRY_CONFIG)


@dataclass(frozen=True)
class Entry:
    """One log slot. ``index`` is stored redundantly so that an entry copied
    into a message keeps its identity, and so a mismatch between position
    and ``index`` is detectable (:meth:`RaftLog.check`)."""

    index: int
    term: int
    kind: str = ENTRY_COMMAND
    command: Command | None = None
    payload: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.kind not in ENTRY_KINDS:
            raise ValueError(f"unknown entry kind {self.kind!r}; expected one of {ENTRY_KINDS}")
        if self.index < 1:
            raise ValueError("log indexes start at 1")
        if self.term < 1:
            raise ValueError("a log entry carries the term that created it, which is at least 1")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"index": self.index, "term": self.term, "kind": self.kind}
        if self.command is not None:
            out["command"] = self.command.to_dict()
        if self.payload is not None:
            out["payload"] = dict(self.payload)
        return out

    def summary(self) -> str:
        if self.kind == ENTRY_COMMAND and self.command is not None:
            return f"{self.index}/{self.term}:{self.command.summary()}"
        return f"{self.index}/{self.term}:{self.kind}"


def entry_from_dict(data: dict[str, Any]) -> Entry:
    command = data.get("command")
    return Entry(
        index=int(data["index"]),
        term=int(data["term"]),
        kind=data.get("kind", ENTRY_COMMAND),
        command=command_from_dict(command) if command is not None else None,
        payload=dict(data["payload"]) if data.get("payload") is not None else None,
    )


class RaftLog:
    """The log of one node.

    The log never allocates index numbers itself for leader appends — the
    node computes ``last_index + 1`` and builds the entry — so that an
    entry's index is fixed before it is handed to storage or to a message.
    """

    def __init__(
        self,
        entries: Iterable[Entry] = (),
        base_index: int = 0,
        base_term: int = 0,
    ) -> None:
        if base_index < 0 or base_term < 0:
            raise StorageError("the compacted prefix cannot have a negative index or term")
        if (base_index == 0) != (base_term == 0):
            raise StorageError("base_index and base_term are both zero or both positive")
        self.base_index = base_index
        self.base_term = base_term
        self._entries: list[Entry] = list(entries)
        self.check()

    # -- shape ------------------------------------------------------------

    def check(self) -> None:
        """Raise :class:`StorageError` if the entries are not dense from
        ``base_index + 1`` or if terms ever decrease."""

        expected = self.base_index + 1
        previous_term = self.base_term
        for entry in self._entries:
            if entry.index != expected:
                raise StorageError(f"log is not dense: expected index {expected}, found {entry.index}")
            if entry.term < previous_term:
                raise StorageError(
                    f"terms decrease at index {entry.index}: {previous_term} -> {entry.term}"
                )
            expected += 1
            previous_term = entry.term

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def first_index(self) -> int:
        return self.base_index + 1

    @property
    def last_index(self) -> int:
        return self.base_index + len(self._entries)

    @property
    def last_term(self) -> int:
        if self._entries:
            return self._entries[-1].term
        return self.base_term

    def entries(self) -> tuple[Entry, ...]:
        return tuple(self._entries)

    def contains(self, index: int) -> bool:
        return self.first_index <= index <= self.last_index

    def at(self, index: int) -> Entry:
        if not self.contains(index):
            raise IndexError(f"index {index} is not in the log [{self.first_index}, {self.last_index}]")
        return self._entries[index - self.first_index]

    def term_at(self, index: int) -> int | None:
        """The term at ``index``: 0 for the empty prefix, the snapshot term at
        ``base_index``, ``None`` for an index the log does not hold."""

        if index == 0:
            return 0
        if index == self.base_index:
            return self.base_term
        if self.contains(index):
            return self.at(index).term
        return None

    def slice(self, start: int, limit: int | None = None) -> tuple[Entry, ...]:
        """Entries from ``start`` inclusive, at most ``limit`` of them."""

        if start < self.first_index:
            raise IndexError(f"index {start} was compacted away (first is {self.first_index})")
        if start > self.last_index:
            return ()
        begin = start - self.first_index
        end = len(self._entries) if limit is None else min(len(self._entries), begin + limit)
        return tuple(self._entries[begin:end])

    def first_index_of_term(self, term: int) -> int | None:
        for entry in self._entries:
            if entry.term == term:
                return entry.index
        return None

    # -- rules --------------------------------------------------------------

    def matches(self, prev_index: int, prev_term: int) -> bool:
        """The log-matching check of ``SPEC.md`` section 3.2."""

        term = self.term_at(prev_index)
        return term is not None and term == prev_term

    def is_up_to_date(self, last_index: int, last_term: int) -> bool:
        """True if a log ending in ``(last_index, last_term)`` is at least as
        up to date as this one (``SPEC.md`` section 2.6)."""

        if last_term != self.last_term:
            return last_term > self.last_term
        return last_index >= self.last_index

    def conflict_hint(self, prev_index: int) -> tuple[int, int]:
        """What a rejecting follower tells the leader: the term of its entry
        at ``prev_index`` and the first index of that term, or
        ``(last_index + 1, 0)`` if it has no entry there."""

        term = self.term_at(prev_index)
        if term is None or prev_index > self.last_index:
            return self.last_index + 1, 0
        first = self.first_index_of_term(term)
        return (first if first is not None else self.first_index), term

    # -- mutation -----------------------------------------------------------

    def append(self, entry: Entry) -> Entry:
        """Leader-side append. The entry's index must be ``last_index + 1``."""

        if entry.index != self.last_index + 1:
            raise StorageError(f"append out of order: expected {self.last_index + 1}, got {entry.index}")
        if entry.term < self.last_term:
            raise StorageError("a new entry cannot carry a term lower than the last entry's")
        self._entries.append(entry)
        return entry

    def truncate_from(self, index: int) -> int:
        """Drop ``index`` and everything after it; return how many entries
        went. Refuses to cut into the compacted prefix."""

        if index <= self.base_index:
            raise StorageError(f"cannot truncate into the compacted prefix (index {index})")
        if index > self.last_index:
            return 0
        removed = self.last_index - index + 1
        del self._entries[index - self.first_index:]
        return removed

    def append_from_leader(
        self, prev_index: int, prev_term: int, entries: Sequence[Entry]
    ) -> tuple[bool, int, int, int]:
        """Apply an ``AppendEntries`` payload.

        Returns ``(accepted, truncated, appended, match_index)``. When the
        prefix does not match, nothing changes and ``accepted`` is false.
        When it matches, entries already present with the same term are
        skipped; the first entry whose term differs from the one already at
        its index triggers a truncation from that index, after which the
        remaining entries are appended. ``match_index`` is
        ``prev_index + len(entries)``, the last index the follower now knows
        agrees with the leader.
        """

        if not self.matches(prev_index, prev_term):
            return False, 0, 0, 0
        truncated = 0
        appended = 0
        for entry in entries:
            existing = self.term_at(entry.index)
            if existing is None:
                self.append(entry)
                appended += 1
            elif existing != entry.term:
                truncated += self.truncate_from(entry.index)
                self.append(entry)
                appended += 1
            # else: identical entry already present — keep it.
        return True, truncated, appended, prev_index + len(entries)

    # -- compaction seam (declared) --------------------------------------

    def compact_to(self, last_included_index: int, last_included_term: int) -> int:
        """Forget entries up to and including ``last_included_index``,
        remembering the term of the boundary. Returns how many entries were
        dropped. The seed never calls this; ``tidewater.snapshot`` will."""

        if last_included_index <= self.base_index:
            return 0
        if last_included_index > self.last_index:
            raise StorageError("cannot compact past the end of the log")
        if self.term_at(last_included_index) != last_included_term:
            raise StorageError("the compaction boundary term does not match the log")
        dropped = last_included_index - self.base_index
        del self._entries[:dropped]
        self.base_index = last_included_index
        self.base_term = last_included_term
        return dropped

    # -- rendering ---------------------------------------------------------

    def summary(self) -> str:
        if not self._entries:
            return f"[base {self.base_index}/{self.base_term}] empty"
        shown = " ".join(e.summary() for e in self._entries[-6:])
        prefix = "... " if len(self._entries) > 6 else ""
        return f"[base {self.base_index}/{self.base_term}] {prefix}{shown}"

    def terms(self) -> list[int]:
        return [e.term for e in self._entries]

    def to_dicts(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._entries]
