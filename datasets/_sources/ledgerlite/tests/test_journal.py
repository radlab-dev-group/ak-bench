"""The journal takes only balanced entries, and balances accounts on their own side."""

from datetime import UTC, datetime

import pytest
from ledgerlite.accounts import Account, AccountType, Chart
from ledgerlite.errors import DuplicateEntryId, UnbalancedEntry
from ledgerlite.journal import Entry, Journal, Posting

MOMENT = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)


def a_chart() -> Chart:
    return Chart(
        [
            Account("1000", "Cash", AccountType.ASSET, "EUR"),
            Account("2000", "Supplier", AccountType.LIABILITY, "EUR"),
            Account("6000", "Rent", AccountType.EXPENSE, "EUR"),
        ]
    )


def an_entry(entry_id: str, *postings: Posting) -> Entry:
    return Entry(entry_id=entry_id, booked_at=MOMENT, description="test", postings=list(postings))


def debit(code: str, cents: int, currency: str = "EUR") -> Posting:
    return Posting(account=code, side="debit", cents=cents, currency=currency)


def credit(code: str, cents: int, currency: str = "EUR") -> Posting:
    return Posting(account=code, side="credit", cents=cents, currency=currency)


def test_a_balanced_entry_is_accepted():
    journal = Journal(a_chart())
    journal.post(an_entry("e1", debit("6000", 500), credit("1000", 500)))
    assert len(journal) == 1


def test_an_unbalanced_entry_is_refused_and_nothing_is_stored():
    journal = Journal(a_chart())
    with pytest.raises(UnbalancedEntry):
        journal.post(an_entry("e1", debit("6000", 500), credit("1000", 400)))
    assert len(journal) == 0


def test_an_entry_id_cannot_be_posted_twice():
    journal = Journal(a_chart())
    journal.post(an_entry("e1", debit("6000", 500), credit("1000", 500)))
    with pytest.raises(DuplicateEntryId):
        journal.post(an_entry("e1", debit("6000", 100), credit("1000", 100)))


def test_an_account_balance_is_expressed_on_its_normal_side():
    journal = Journal(a_chart())
    journal.post(an_entry("e1", debit("1000", 900), credit("2000", 900)))
    journal.post(an_entry("e2", debit("2000", 400), credit("1000", 400)))
    assert journal.balance("1000") == {"EUR": 500}
    assert journal.balance("2000") == {"EUR": 500}


def test_a_window_excludes_its_end_instant():
    journal = Journal(a_chart())
    journal.post(an_entry("e1", debit("6000", 10), credit("1000", 10)))
    inside = journal.booked_between(MOMENT, MOMENT.replace(hour=10))
    outside = journal.booked_between(MOMENT.replace(hour=10), MOMENT.replace(hour=11))
    assert [entry.entry_id for entry in inside] == ["e1"]
    assert outside == []
