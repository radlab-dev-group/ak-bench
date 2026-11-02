"""The journal: entries, postings, and the rule that keeps them balanced.

A posting says that one account gained on one side. An entry is a set of
postings that together describe one business event, and the journal is the
append-only sequence of entries.

The balance rule
    For every currency that appears in an entry, the debits and the credits of
    that currency have to cancel out exactly. An entry in one currency is
    therefore the familiar "debits equal credits"; a currency-pair entry is two
    balanced halves glued together — the foreign side and the home side — and
    it is refused if either half is off by a cent. An entry with no postings
    balances trivially and is refused as well: it says nothing.

    ``Journal.post`` is the only way in, and it refuses an unbalanced entry
    before the entry exists. The journal therefore cannot hold a broken state,
    which is what lets everything downstream trust it without re-checking.

Immutability
    The journal stores its own list and hands out copies of it. Nothing here
    changes a posted entry; correcting a mistake means posting another entry.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from ledgerlite.accounts import Chart, Side
from ledgerlite.errors import DuplicateEntryId, UnbalancedEntry, UnknownEntry


@dataclass(frozen=True)
class Posting:
    """One account, one side, one amount."""

    account: str
    side: Side
    cents: int
    currency: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "side", Side(self.side))
        if self.cents < 0:
            raise ValueError(f"a posting amount cannot be negative, got {self.cents}")


@dataclass
class Entry:
    """A balanced set of postings, booked at one instant.

    ``reference`` is the number the outside world uses for the same event — an
    invoice number, a transfer reference — and it is what lets a bank statement
    find an entry it cannot find by date.
    """

    entry_id: str
    booked_at: datetime
    description: str
    postings: list[Posting] = field(default_factory=list)
    reference: str | None = None

    def add(self, posting: Posting) -> Posting:
        self.postings.append(posting)
        return posting

    def currency_totals(self) -> dict[str, dict[str, int]]:
        """Per currency: how much was debited and how much credited."""
        totals: dict[str, dict[str, int]] = {}
        for posting in self.postings:
            row = totals.setdefault(posting.currency, {"debit": 0, "credit": 0})
            row[posting.side] += posting.cents
        return totals

    def is_balanced(self) -> bool:
        """Whether every currency in the entry cancels out, and it says something."""
        if not self.postings:
            return False
        return all(row["debit"] == row["credit"] for row in self.currency_totals().values())

    def difference(self, currency: str) -> int:
        """How far the entry is from balanced in one currency, in cents."""
        row = self.currency_totals().get(currency, {"debit": 0, "credit": 0})
        return row["debit"] - row["credit"]

    def currencies(self) -> list[str]:
        return sorted(self.currency_totals())

    def accounts(self) -> list[str]:
        return sorted({posting.account for posting in self.postings})


class Journal:
    """The append-only sequence of balanced entries."""

    def __init__(self, chart: Chart) -> None:
        self.chart = chart
        self._entries: list[Entry] = []
        self._by_id: dict[str, Entry] = {}

    def post(self, entry: Entry) -> Entry:
        """Add an entry, refusing an id already used and an entry out of balance.

        The chart is checked first, so a posting to an unknown account is a
        clearer error than an unbalanced entry; nothing is stored when either
        check fails.
        """
        if entry.entry_id in self._by_id:
            raise DuplicateEntryId(entry.entry_id)
        for posting in entry.postings:
            self.chart.require(posting.account)
        if not entry.postings:
            raise UnbalancedEntry(entry.entry_id, "-", 0)
        for currency in entry.currencies():
            difference = entry.difference(currency)
            if difference:
                raise UnbalancedEntry(entry.entry_id, currency, difference)
        self._entries.append(entry)
        self._by_id[entry.entry_id] = entry
        return entry

    def get(self, entry_id: str) -> Entry:
        try:
            return self._by_id[entry_id]
        except KeyError:
            raise UnknownEntry(entry_id) from None

    def entries(self) -> list[Entry]:
        """Every entry, in the order it was posted."""
        return list(self._entries)

    def booked_between(self, start: datetime, end: datetime) -> list[Entry]:
        """Entries booked in ``[start, end)`` — start inclusive, end exclusive."""
        return [
            entry
            for entry in self._entries
            if start <= entry.booked_at < end
        ]

    def postings_for(self, account: str) -> list[tuple[Entry, Posting]]:
        """Every posting to one account, paired with the entry that carries it."""
        found: list[tuple[Entry, Posting]] = []
        for entry in self._entries:
            for posting in entry.postings:
                if posting.account == account:
                    found.append((entry, posting))
        return found

    def balance(self, account: str) -> dict[str, int]:
        """The account's balance per currency, on its normal side.

        A debit-normal account with 100 debits and 40 credits is 60; the same
        postings on a credit-normal account would be -60, which is what a
        debit-normal balance sitting in a credit account looks like.
        """
        normal = self.chart.require(account).normal_side
        totals: dict[str, int] = {}
        for _entry, posting in self.postings_for(account):
            sign = 1 if posting.side is normal else -1
            totals[posting.currency] = totals.get(posting.currency, 0) + sign * posting.cents
        return {currency: value for currency, value in sorted(totals.items()) if value}

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterable[Entry]:
        return iter(list(self._entries))
