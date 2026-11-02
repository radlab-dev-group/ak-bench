"""What a developer can check without the hidden cases: the shape of an answer."""

from datetime import UTC, date, datetime

from ledgerlite.accounts import Account, AccountType, Chart
from ledgerlite.journal import Entry, Journal, Posting
from ledgerlite.reconcile import Reconciliation, StatementLine, reconcile

ACCOUNT = "1000"


def a_journal() -> Journal:
    return Journal(
        Chart(
            [
                Account(ACCOUNT, "Bank", AccountType.ASSET, "EUR"),
                Account("7000", "Sales", AccountType.REVENUE, "EUR"),
            ]
        )
    )


def book(
    journal: Journal,
    entry_id: str,
    on: datetime,
    cents: int,
    reference: str | None = None,
) -> None:
    side = "debit" if cents >= 0 else "credit"
    journal.post(
        Entry(
            entry_id=entry_id,
            booked_at=on,
            description=entry_id,
            postings=[
                Posting(account=ACCOUNT, side=side, cents=abs(cents), currency="EUR"),
                Posting(
                    account="7000",
                    side="credit" if cents >= 0 else "debit",
                    cents=abs(cents),
                    currency="EUR",
                ),
            ],
            reference=reference,
        )
    )


def line(line_id: str, day: int, cents: int, reference: str | None = None) -> StatementLine:
    return StatementLine(
        line_id=line_id,
        booked_on=date(2026, 5, day),
        cents=cents,
        currency="EUR",
        reference=reference,
    )


def at(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 5, day, hour, 0, tzinfo=UTC)


def test_an_empty_statement_reconciles_to_nothing():
    result = reconcile(a_journal(), [], account=ACCOUNT)
    assert isinstance(result, Reconciliation)
    assert result.matches == []
    assert result.unmatched_lines == []
    assert result.difference_cents == 0


def test_a_line_and_a_booking_that_agree_are_matched():
    journal = a_journal()
    book(journal, "e1", at(10), 5000)
    result = reconcile(journal, [line("s1", 10, 5000)], account=ACCOUNT)
    assert result.matched_entry_ids() == ["e1"]
    assert result.is_complete()


def test_a_line_nothing_matches_is_reported_and_counts_toward_the_difference():
    journal = a_journal()
    result = reconcile(journal, [line("s1", 10, 5000)], account=ACCOUNT)
    assert result.unmatched_lines == ["s1"]
    assert result.difference_cents == 5000


def test_an_unclaimed_booking_stays_open():
    journal = a_journal()
    book(journal, "e1", at(10), 5000)
    result = reconcile(journal, [], account=ACCOUNT)
    assert result.open_candidates == ["e1"]
