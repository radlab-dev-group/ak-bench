"""The reconciliation contract, enforced on the answer the agent hands back.

Every rule in the module docstring has a test here: the exact-amount rule, the
window and how days are counted, how ties are broken, what the two passes do
and in which order, what stays open, and that the whole thing is pure.
"""

from datetime import UTC, date, datetime

from ledgerlite.accounts import Account, AccountType, Chart
from ledgerlite.journal import Entry, Journal, Posting
from ledgerlite.reconcile import Match, StatementLine, reconcile

BANK = "1000"


def a_journal() -> Journal:
    return Journal(
        Chart(
            [
                Account(BANK, "Bank", AccountType.ASSET, "EUR"),
                Account("2000", "Supplier", AccountType.LIABILITY, "EUR"),
                Account("7000", "Sales", AccountType.REVENUE, "EUR"),
            ]
        )
    )


def book(
    journal: Journal,
    entry_id: str,
    on: datetime,
    cents: int,
    *,
    reference: str | None = None,
    currency: str = "EUR",
) -> None:
    """Post one balanced entry whose bank posting carries ``cents``."""
    side = "debit" if cents >= 0 else "credit"
    postings = [Posting(account=BANK, side=side, cents=abs(cents), currency=currency)]
    other_side = "credit" if cents >= 0 else "debit"
    postings.append(
        Posting(account="7000", side=other_side, cents=abs(cents), currency=currency)
    )
    entry = Entry(
        entry_id=entry_id,
        booked_at=on,
        description=entry_id,
        postings=postings,
        reference=reference,
    )
    journal.post(entry)


def line(
    line_id: str,
    day: int,
    cents: int,
    *,
    reference: str | None = None,
    currency: str = "EUR",
) -> StatementLine:
    return StatementLine(
        line_id=line_id,
        booked_on=date(2026, 5, day),
        cents=cents,
        currency=currency,
        reference=reference,
    )


def at(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 5, day, hour, 0, tzinfo=UTC)


# ------------------------------------------------------------ the exact rule


def test_the_amount_must_be_exact_and_signed():
    journal = a_journal()
    book(journal, "e1", at(10), 5000)
    result = reconcile(journal, [line("s1", 10, 5001)], account=BANK)
    assert result.unmatched_lines == ["s1"]
    result = reconcile(journal, [line("s1", 10, -5000)], account=BANK)
    assert result.unmatched_lines == ["s1"]


def test_a_candidate_in_another_currency_is_not_a_candidate():
    journal = a_journal()
    book(journal, "e1", at(10), 5000, currency="USD")
    result = reconcile(journal, [line("s1", 10, 5000)], account=BANK)
    assert result.unmatched_lines == ["s1"]


# ------------------------------------------------------------------ the window


def test_a_booking_exactly_at_the_edge_of_the_window_still_counts():
    journal = a_journal()
    book(journal, "e1", at(13), 5000)
    result = reconcile(journal, [line("s1", 10, 5000)], account=BANK, window_days=3)
    assert result.matched_entry_ids() == ["e1"]


def test_a_booking_one_day_outside_the_window_does_not():
    journal = a_journal()
    book(journal, "e1", at(14), 5000)
    result = reconcile(journal, [line("s1", 10, 5000)], account=BANK, window_days=3)
    assert result.unmatched_lines == ["s1"]


def test_days_are_whole_days_and_ignore_the_time_of_day():
    """A booking at 23:00 and a line dated the next morning are one day apart."""
    journal = a_journal()
    book(journal, "e1", at(13, 23), 5000)
    result = reconcile(journal, [line("s1", 14, 5000)], account=BANK, window_days=1)
    assert result.matched_entry_ids() == ["e1"]


# ------------------------------------------------------------- closest wins


def test_the_closest_booking_wins_over_the_earlier_one():
    journal = a_journal()
    book(journal, "e-early", at(7), 5000)
    book(journal, "e-close", at(12), 5000)
    result = reconcile(journal, [line("s1", 10, 5000)], account=BANK)
    assert result.matched_entry_ids() == ["e-close"]


def test_two_bookings_equally_close_take_the_earlier_date_then_the_smaller_id():
    journal = a_journal()
    book(journal, "e-later-same-day", at(10, 18), 5000)
    book(journal, "e-earlier-same-day", at(10, 6), 5000)
    result = reconcile(journal, [line("s1", 10, 5000)], account=BANK)
    assert result.matched_entry_ids() == ["e-earlier-same-day"]
    journal = a_journal()
    book(journal, "e-b", at(11), 5000)
    book(journal, "e-a", at(9), 5000)
    result = reconcile(journal, [line("s1", 10, 5000)], account=BANK)
    assert result.matched_entry_ids() == ["e-a"]


# ------------------------------------------------------------- one claim each


def test_one_candidate_cannot_be_claimed_by_two_lines():
    journal = a_journal()
    book(journal, "e1", at(10), 5000)
    result = reconcile(journal, [line("s1", 10, 5000), line("s2", 10, 5000)], account=BANK)
    assert sorted(result.matched_line_ids()) == ["s1"]
    assert result.unmatched_lines == ["s2"]


def test_a_posting_to_another_account_is_not_a_candidate():
    """An entry may carry 5000 on a non-bank account; that is not the bank's money."""
    journal = a_journal()
    journal.post(
        Entry(
            entry_id="e1",
            booked_at=at(10),
            description="e1",
            postings=[
                Posting(account=BANK, side="debit", cents=5000, currency="EUR"),
                Posting(account=BANK, side="credit", cents=4000, currency="EUR"),
                Posting(account="2000", side="credit", cents=2000, currency="EUR"),
                Posting(account="2000", side="debit", cents=1000, currency="EUR"),
            ],
        )
    )
    result = reconcile(journal, [line("s1", 10, 2000)], account=BANK)
    assert result.matches == []
    assert result.open_candidates == ["e1"]


# ------------------------------------------------------------- line ordering


def test_lines_are_considered_oldest_first_and_ties_take_the_smaller_id():
    """Two lines on one day: the smaller id chooses first and takes the closest entry."""
    journal = a_journal()
    book(journal, "e-close", at(12), 5000)
    book(journal, "e-far", at(9), 5000)
    result = reconcile(journal, [line("s-b", 12, 5000), line("s-a", 12, 5000)], account=BANK)
    assert result.matches[0].line_id == "s-a"
    chosen = {match.line_id: match.entry_id for match in result.matches}
    assert chosen == {"s-a": "e-close", "s-b": "e-far"}


# ------------------------------------------------------------------ pass two


def test_a_reference_matches_a_line_outside_the_window():
    journal = a_journal()
    book(journal, "e1", at(1), 7777, reference="INV-9")
    statement = [line("s1", 28, 7777, reference="INV-9")]
    result = reconcile(journal, statement, account=BANK, window_days=3)
    assert result.matched_entry_ids() == ["e1"]
    assert result.matches[0].days_apart == 27


def test_pass_two_still_requires_the_amount_to_be_exact():
    journal = a_journal()
    book(journal, "e1", at(1), 7777, reference="INV-9")
    result = reconcile(journal, [line("s1", 28, 7776, reference="INV-9")], account=BANK)
    assert result.unmatched_lines == ["s1"]


def test_a_line_without_a_reference_has_no_second_chance():
    journal = a_journal()
    book(journal, "e1", at(1), 7777, reference="INV-9")
    result = reconcile(journal, [line("s1", 28, 7777)], account=BANK)
    assert result.unmatched_lines == ["s1"]


def test_an_entry_without_a_reference_cannot_be_found_by_one():
    journal = a_journal()
    book(journal, "e1", at(1), 7777)
    result = reconcile(journal, [line("s1", 28, 7777, reference="INV-9")], account=BANK)
    assert result.unmatched_lines == ["s1"]


def test_the_window_pass_chooses_before_the_reference_pass():
    journal = a_journal()
    book(journal, "e-window", at(10), 5000, reference="INV-1")
    book(journal, "e-reference", at(1), 5000, reference="INV-1")
    result = reconcile(journal, [line("s1", 10, 5000, reference="INV-1")], account=BANK)
    assert result.matched_entry_ids() == ["e-window"]


# ------------------------------------------------------------------- open


def test_an_entry_whose_every_candidate_was_claimed_is_not_open():
    journal = a_journal()
    book(journal, "e1", at(10), 5000)
    book(journal, "e2", at(11), 6000)
    result = reconcile(journal, [line("s1", 10, 5000)], account=BANK)
    assert result.open_candidates == ["e2"]


def test_open_candidates_are_sorted_by_booking_then_id():
    journal = a_journal()
    book(journal, "e-late", at(20), 100)
    book(journal, "e-early", at(5), 100)
    result = reconcile(journal, [], account=BANK)
    assert result.open_candidates == ["e-early", "e-late"]


# ------------------------------------------------------------- the answer


def test_matches_carry_the_days_apart_and_are_ordered_by_the_line():
    journal = a_journal()
    book(journal, "e1", at(11), 5000)
    book(journal, "e2", at(9), 5000)
    result = reconcile(journal, [line("s-b", 11, 5000), line("s-a", 9, 5000)], account=BANK)
    assert [match.line_id for match in result.matches] == ["s-a", "s-b"]
    by_line = {match.line_id: match.days_apart for match in result.matches}
    assert by_line == {"s-a": 0, "s-b": 0}


def test_the_difference_is_the_sum_of_the_unmatched_amounts():
    journal = a_journal()
    book(journal, "e1", at(10), 5000)
    result = reconcile(journal, [line("s1", 10, 5000), line("s2", 10, 2500)], account=BANK)
    assert result.difference_cents == 2500
    assert not result.is_complete()


def test_the_answer_is_pure_and_deterministic():
    journal = a_journal()
    book(journal, "e1", at(11), 5000)
    book(journal, "e2", at(9), 5000)
    statement = [line("s-b", 11, 5000), line("s-a", 9, 5000)]
    first = reconcile(journal, statement, account=BANK)
    second = reconcile(journal, statement, account=BANK)
    assert first == second
    assert first.matches and all(isinstance(match, Match) for match in first.matches)
