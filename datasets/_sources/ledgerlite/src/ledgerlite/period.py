"""Accounting periods: a half-open window, a trial balance, and the close.

A period is ``[start, end)`` — the first instant belongs to it, the last does
not. That is the whole definition and everything else follows from it: an entry
booked exactly at ``end`` belongs to the next period, and two periods that share
a boundary do not overlap.

The trial balance
    The net movement of every account that has a posting in the window, per
    currency, expressed on the account's normal side. It is a *movement* report,
    not a running balance: an account whose debits and credits cancel inside the
    window does not appear, because in this window nothing happened to it.

    A trial balance is a check on the journal, not on the chart: the debits and
    credits of every currency have to be equal in total, because every entry
    that got posted was balanced when it went in.

Closing
    Closing a period moves the result of the period — revenue minus expenses —
    into equity. The closing entry debits every revenue account for its balance
    in the window and credits every expense account for its balance, with the
    difference against the retained-earnings account, so after the close the
    result accounts are empty and the equity account carries the profit or loss.
    The entry is booked at an instant the caller supplies, because where the
    close belongs is an accounting decision, not a code decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from itertools import pairwise

from ledgerlite.accounts import AccountType, Chart, Side
from ledgerlite.errors import NothingToClose, OverlappingPeriod
from ledgerlite.journal import Entry, Journal, Posting

#: The account types a close empties out.
RESULT_TYPES: frozenset[AccountType] = frozenset({AccountType.REVENUE, AccountType.EXPENSE})


@dataclass(frozen=True)
class Period:
    """A named half-open window: ``[start, end)``."""

    name: str
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"period {self.name} ends before it starts")

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end

    def overlaps(self, other: Period) -> bool:
        return self.start < other.end and other.start < self.end

    def __contains__(self, moment: object) -> bool:
        return isinstance(moment, datetime) and self.contains(moment)


def assert_no_overlaps(periods: list[Period]) -> list[Period]:
    """Refuse a calendar in which two periods cover the same instant."""
    ordered = sorted(periods, key=lambda period: (period.start, period.name))
    for earlier, later in pairwise(ordered):
        if earlier.overlaps(later):
            raise OverlappingPeriod(earlier.name, later.name)
    return ordered


@dataclass(frozen=True)
class Movement:
    """One account's movement in a window, on its normal side."""

    account: str
    currency: str
    debit_cents: int
    credit_cents: int

    @property
    def net_cents(self) -> int:
        """Debits minus credits; the sign before the normal side is applied."""
        return self.debit_cents - self.credit_cents

    def on_side(self, normal: Side) -> int:
        """The movement expressed as a positive number when it grows the account."""
        return self.net_cents if normal is Side.DEBIT else -self.net_cents


@dataclass
class TrialBalance:
    """Every account that moved in a window, and the totals that check them."""

    period: Period
    movements: list[Movement] = field(default_factory=list)

    def totals(self) -> dict[str, dict[str, int]]:
        """Per currency: total debits and total credits in the window."""
        totals: dict[str, dict[str, int]] = {}
        for movement in self.movements:
            row = totals.setdefault(movement.currency, {"debit": 0, "credit": 0})
            row["debit"] += movement.debit_cents
            row["credit"] += movement.credit_cents
        return totals

    def account(self, code: str) -> Movement | None:
        for movement in self.movements:
            if movement.account == code:
                return movement
        return None

    def is_balanced(self) -> bool:
        return all(row["debit"] == row["credit"] for row in self.totals().values())


def trial_balance(journal: Journal, period: Period) -> TrialBalance:
    """The movement of every account inside ``period``."""
    totals: dict[tuple[str, str], Movement] = {}
    for entry in journal.booked_between(period.start, period.end):
        for posting in entry.postings:
            key = (posting.account, posting.currency)
            current = totals.get(key)
            debits = posting.cents if posting.side is Side.DEBIT else 0
            credits = posting.cents if posting.side is Side.CREDIT else 0
            if current is None:
                totals[key] = Movement(posting.account, posting.currency, debits, credits)
            else:
                totals[key] = Movement(
                    posting.account,
                    posting.currency,
                    current.debit_cents + debits,
                    current.credit_cents + credits,
                )
    return TrialBalance(
        period=period,
        movements=[totals[key] for key in sorted(totals)],
    )


def close(
    journal: Journal,
    chart: Chart,
    period: Period,
    *,
    retained_earnings: str,
    entry_id: str,
    booked_at: datetime,
) -> Entry:
    """Post the closing entry for ``period`` against the retained-earnings account.

    Every revenue and expense account with a movement in the window is emptied:
    revenue is debited for its credit balance, expense is credited for its debit
    balance. Whatever is left over is the period's result, and it lands on
    ``retained_earnings`` — a credit when the period made money, a debit when it
    lost some. A period with no movement in a result account has nothing to
    close, and closing it raises :class:`~ledgerlite.errors.NothingToClose`
    rather than post an entry that says nothing.
    """
    balance = trial_balance(journal, period)
    postings: list[Posting] = []
    currency = next((movement.currency for movement in balance.movements), journal_home(chart))

    for movement in balance.movements:
        account = chart.require(movement.account)
        if account.type not in RESULT_TYPES:
            continue
        if movement.net_cents == 0:
            continue
        # Zero the account: a revenue (credit balance) is closed by a debit, an
        # expense (debit balance) by a credit.
        side = Side.DEBIT if movement.net_cents < 0 else Side.CREDIT
        postings.append(
            Posting(
                account=account.code,
                side=side,
                cents=abs(movement.net_cents),
                currency=movement.currency,
            )
        )

    if not postings:
        raise NothingToClose(period.name)

    remaining = sum(
        posting.cents if posting.side is Side.DEBIT else -posting.cents for posting in postings
    )
    if remaining:
        postings.append(
            Posting(
                account=retained_earnings,
                side=Side.CREDIT if remaining > 0 else Side.DEBIT,
                cents=abs(remaining),
                currency=currency,
            )
        )
    entry = Entry(
        entry_id=entry_id,
        booked_at=booked_at,
        description=f"close {period.name}",
    )
    for posting in postings:
        entry.add(posting)
    return journal.post(entry)


def journal_home(chart: Chart) -> str:
    """The currency the chart is mostly kept in — the first account's, alphabetically."""
    codes = chart.codes()
    if not codes:
        raise ValueError("an empty chart has no home currency")
    return chart.require(codes[0]).currency
