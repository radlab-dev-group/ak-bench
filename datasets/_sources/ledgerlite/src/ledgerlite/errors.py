"""The whole exception hierarchy of the ledger.

Every failure the ledger can produce is a :class:`LedgerError`, so a caller can
catch one name. The subclasses carry the identifying fields of whatever was
refused, because "the entry is unbalanced" is only useful when it says which
entry and by how much.
"""

from __future__ import annotations


class LedgerError(Exception):
    """Base class for everything ledgerlite refuses."""


class UnknownAccount(LedgerError):
    """A posting names an account the chart does not hold."""

    def __init__(self, code: str) -> None:
        super().__init__(f"unknown account: {code}")
        self.code = code


class DuplicateAccount(LedgerError):
    """The chart already holds an account with this code."""

    def __init__(self, code: str) -> None:
        super().__init__(f"account already exists: {code}")
        self.code = code


class UnknownEntry(LedgerError):
    """The journal holds no entry with this id."""

    def __init__(self, entry_id: str) -> None:
        super().__init__(f"unknown entry: {entry_id}")
        self.entry_id = entry_id


class DuplicateEntryId(LedgerError):
    """An entry id can be posted once; the journal is append-only."""

    def __init__(self, entry_id: str) -> None:
        super().__init__(f"entry already posted: {entry_id}")
        self.entry_id = entry_id


class UnbalancedEntry(LedgerError):
    """Debits and credits of one currency in an entry do not cancel out."""

    def __init__(self, entry_id: str, currency: str, difference_cents: int) -> None:
        super().__init__(
            f"entry {entry_id} is unbalanced in {currency} by {difference_cents} cents"
        )
        self.entry_id = entry_id
        self.currency = currency
        self.difference_cents = difference_cents


class MissingRate(LedgerError):
    """The rate book has no rate to convert with at the requested moment."""

    def __init__(self, currency: str, at: object) -> None:
        super().__init__(f"no {currency} rate in force at {at}")
        self.currency = currency
        self.at = at


class NothingToClose(LedgerError):
    """A period with no movement in a result account cannot be closed."""

    def __init__(self, period: str) -> None:
        super().__init__(f"nothing to close in period: {period}")
        self.period = period


class OverlappingPeriod(LedgerError):
    """Two accounting periods cover the same instant."""

    def __init__(self, first: str, second: str) -> None:
        super().__init__(f"periods overlap: {first} and {second}")
        self.first = first
        self.second = second
