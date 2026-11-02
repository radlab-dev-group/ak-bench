"""The chart of accounts: what exists, which side it grows on.

An account belongs to exactly one of the five types, and its type decides the
side the account grows on — its **normal side**. Assets and expenses grow on
the debit side; liabilities, equity and revenue grow on the credit side. The
normal side is what makes a balance readable: a cash account with 100 debits
and 40 credits is a debit balance of 60, not a credit balance of -60.

The chart is the only place an account code becomes legal. A posting that
names a code the chart does not hold is refused rather than ignored, because a
ledger with a typo in it balances and lies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ledgerlite.errors import DuplicateAccount, UnknownAccount


class Side(StrEnum):
    """The two sides of a double-entry posting."""

    DEBIT = "debit"
    CREDIT = "credit"

    def other(self) -> Side:
        return Side.CREDIT if self is Side.DEBIT else Side.DEBIT


class AccountType(StrEnum):
    """The five classes of account; the type decides the normal side."""

    ASSET = "asset"
    EXPENSE = "expense"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"


#: The types that grow on the debit side; everything else grows on the credit side.
DEBIT_NORMAL: frozenset[AccountType] = frozenset({AccountType.ASSET, AccountType.EXPENSE})


@dataclass(frozen=True)
class Account:
    """One line of the chart: a code, a name, a type and a home currency."""

    code: str
    name: str
    type: AccountType
    currency: str

    def __post_init__(self) -> None:
        if not self.code or not self.code.strip():
            raise ValueError("an account code cannot be empty")
        if not self.name or not self.name.strip():
            raise ValueError("an account name cannot be empty")

    @property
    def normal_side(self) -> Side:
        return Side.DEBIT if self.type in DEBIT_NORMAL else Side.CREDIT

    def grows_on(self, side: Side) -> bool:
        return self.normal_side is side


class Chart:
    """The set of accounts a ledger is allowed to post to."""

    def __init__(self, accounts: list[Account] | None = None) -> None:
        self._accounts: dict[str, Account] = {}
        for account in accounts or []:
            self.add(account)

    def add(self, account: Account) -> Account:
        if account.code in self._accounts:
            raise DuplicateAccount(account.code)
        self._accounts[account.code] = account
        return account

    def require(self, code: str) -> Account:
        try:
            return self._accounts[code]
        except KeyError:
            raise UnknownAccount(code) from None

    def holds(self, code: str) -> bool:
        return code in self._accounts

    def codes(self) -> list[str]:
        return sorted(self._accounts)

    def of_type(self, *types: AccountType) -> list[Account]:
        wanted = set(types)
        return [
            account
            for code in self.codes()
            if (account := self._accounts[code]).type in wanted
        ]

    def __contains__(self, code: object) -> bool:
        return isinstance(code, str) and code in self._accounts

    def __len__(self) -> int:
        return len(self._accounts)
