"""A period is half-open, a trial balance checks the journal, and a close empties the result."""

from datetime import UTC, datetime

import pytest
from ledgerlite.accounts import Account, AccountType, Chart
from ledgerlite.errors import NothingToClose, OverlappingPeriod
from ledgerlite.journal import Entry, Journal, Posting
from ledgerlite.period import Period, assert_no_overlaps, close, trial_balance


def a_chart() -> Chart:
    return Chart(
        [
            Account("1000", "Cash", AccountType.ASSET, "EUR"),
            Account("2000", "Supplier", AccountType.LIABILITY, "EUR"),
            Account("4000", "Retained earnings", AccountType.EQUITY, "EUR"),
            Account("6000", "Rent", AccountType.EXPENSE, "EUR"),
            Account("7000", "Sales", AccountType.REVENUE, "EUR"),
        ]
    )


def a_journal() -> Journal:
    return Journal(a_chart())


def book(journal: Journal, entry_id: str, moment: datetime, *postings: Posting) -> None:
    entry = Entry(entry_id=entry_id, booked_at=moment, description="test", postings=list(postings))
    journal.post(entry)


def debit(code: str, cents: int) -> Posting:
    return Posting(account=code, side="debit", cents=cents, currency="EUR")


def credit(code: str, cents: int) -> Posting:
    return Posting(account=code, side="credit", cents=cents, currency="EUR")


def test_a_period_holds_its_first_instant_and_not_its_last():
    period = Period("Q1", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 4, 1, tzinfo=UTC))
    assert period.contains(datetime(2026, 1, 1, tzinfo=UTC))
    assert not period.contains(datetime(2026, 4, 1, tzinfo=UTC))


def test_two_periods_that_share_a_boundary_do_not_overlap():
    first = Period("Q1", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 4, 1, tzinfo=UTC))
    second = Period("Q2", datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC))
    assert not first.overlaps(second)
    assert assert_no_overlaps([first, second]) == [first, second]


def test_a_real_overlap_is_refused():
    first = Period("Q1", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 4, 15, tzinfo=UTC))
    second = Period("Q2", datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC))
    with pytest.raises(OverlappingPeriod):
        assert_no_overlaps([first, second])


def test_a_trial_balance_reports_the_movement_of_every_account():
    journal = a_journal()
    period = Period("Q1", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 4, 1, tzinfo=UTC))
    book(
        journal,
        "e1",
        datetime(2026, 2, 1, tzinfo=UTC),
        debit("1000", 1_200),
        credit("7000", 1_200),
    )
    balance = trial_balance(journal, period)
    assert balance.is_balanced()
    assert balance.account("7000").credit_cents == 1_200


def test_a_close_moves_the_result_into_equity():
    journal = a_journal()
    period = Period("Q1", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 4, 1, tzinfo=UTC))
    book(
        journal,
        "e1",
        datetime(2026, 2, 1, tzinfo=UTC),
        debit("1000", 1_200),
        credit("7000", 1_200),
    )
    book(
        journal,
        "e2",
        datetime(2026, 3, 1, tzinfo=UTC),
        debit("6000", 500),
        credit("1000", 500),
    )
    entry = close(
        journal,
        a_chart_with(journal),
        period,
        retained_earnings="4000",
        entry_id="close-q1",
        booked_at=datetime(2026, 3, 31, 23, 0, tzinfo=UTC),
    )
    assert entry.is_balanced()
    assert journal.balance("7000") == {}
    assert journal.balance("6000") == {}
    assert journal.balance("4000") == {"EUR": 700}


def a_chart_with(journal: Journal) -> Chart:
    return journal.chart


def test_a_period_with_no_result_activity_cannot_be_closed():
    journal = a_journal()
    period = Period("Q1", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 4, 1, tzinfo=UTC))
    book(
        journal,
        "e1",
        datetime(2026, 2, 1, tzinfo=UTC),
        debit("1000", 300),
        credit("2000", 300),
    )
    with pytest.raises(NothingToClose):
        close(
            journal,
            journal.chart,
            period,
            retained_earnings="4000",
            entry_id="close-empty",
            booked_at=datetime(2026, 3, 31, tzinfo=UTC),
        )
