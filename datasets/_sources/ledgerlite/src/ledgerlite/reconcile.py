"""Matching a bank statement against the journal. The rules are this docstring.

``reconcile(journal, statement, *, account, window_days=3)`` returns a
:class:`Reconciliation`: which statement lines the journal can account for,
which it cannot, and which journal entries the bank has not confirmed. It is a
pure function — nothing is marked, nothing is posted, and calling it twice on
the same inputs gives the same answer.

The two sides
    A **statement line** carries a date (no time), an amount in the account's
    currency, and optionally a reference. A **journal side candidate** is a
    posting to ``account``, taken together with the entry that carries it; what
    identifies a candidate is its entry id.

    One candidate can be claimed by one statement line, and one statement line
    can claim one candidate. A posting to some other account in the same entry
    is not what is being matched, and does not consume anything.

Pass 1 — the window
    Consider the statement lines in date order, oldest first, and break ties on
    the line id. A line may claim a candidate when all of these hold:

    * the candidate is unclaimed;
    * the candidate is in the line's currency;
    * the candidate's amount is exactly the line's amount. A candidate's amount
      is signed by the account's normal side — an amount that grows the account
      is positive and one that reduces it is negative, which is the way a
      statement writes money in and money out — and it has to be equal exactly,
      with no tolerance and with the sign agreeing, because a payment is not a
      refund;
    * the entry was booked within ``window_days`` days of the line's date,
      counted in whole days in either direction: ``abs((booked - line).days)``
      is at most ``window_days``. An entry booked at 23:00 and a line dated the
      next morning are one day apart, not zero.

    Of the candidates a line could claim, the one booked **closest** to the
    line's date wins. Two candidates booked equally close take the earlier
    booking date; still tied, the lexicographically smaller entry id wins.

Pass 2 — the reference
    A line that pass 1 left alone gets a second chance, and this time the window
    does not apply. It may claim an unclaimed candidate whose entry carries the
    same non-empty reference and whose amount is again exactly equal. Lines are
    again processed oldest first, and among several candidates the earliest
    booking date wins, then the smaller entry id. A line with no reference is
    not eligible for pass 2 at all.

What comes back
    ``matches`` holds one :class:`Match` per claimed pair, ordered by the line's
    date and then its id, each carrying the entry id, the amount, and how many
    days apart the two bookings were. ``unmatched_lines`` lists the ids of the
    lines no pass could place, in the same order the lines were considered.
    ``open_candidates`` lists the ids of entries that carry an unclaimed
    candidate — an entry whose every candidate was claimed is not listed, even
    if it has postings to other accounts.

    ``difference_cents`` is what the statement says that the journal has not
    accounted for: the sum of the amounts of ``unmatched_lines``. An empty
    reconciliation of an empty statement is all zeroes and two empty lists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ledgerlite.journal import Journal


@dataclass(frozen=True)
class StatementLine:
    """One line of a bank statement: a date, an amount, and maybe a reference."""

    line_id: str
    booked_on: date
    cents: int
    currency: str
    reference: str | None = None


@dataclass(frozen=True)
class Match:
    """A statement line and the journal entry the reconciliation claims explain it."""

    line_id: str
    entry_id: str
    cents: int
    days_apart: int


@dataclass
class Reconciliation:
    """The whole answer: what matched, what did not, and what is still open."""

    matches: list[Match] = field(default_factory=list)
    unmatched_lines: list[str] = field(default_factory=list)
    open_candidates: list[str] = field(default_factory=list)
    difference_cents: int = 0

    def matched_line_ids(self) -> list[str]:
        return [match.line_id for match in self.matches]

    def matched_entry_ids(self) -> list[str]:
        return [match.entry_id for match in self.matches]

    def is_complete(self) -> bool:
        """True when the statement is fully explained and nothing is left open."""
        return not self.unmatched_lines and not self.open_candidates and not self.difference_cents


def reconcile(
    journal: Journal,
    statement: list[StatementLine],
    *,
    account: str,
    window_days: int = 3,
) -> Reconciliation:
    """Match ``statement`` against the postings of ``account`` in ``journal``."""
    raise NotImplementedError("reconcile is specified in this module and not yet written")
