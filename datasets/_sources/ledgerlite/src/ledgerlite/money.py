"""Exact money: integer minor units, and the two rules that touch them.

Every amount in ledgerlite is an integer number of minor units (cents) of one
currency. There is no floating point anywhere in this package, because a ledger
that is half a cent off is not a ledger.

The two rules
    ``allocate``
        Shares an amount over integer weights so that the parts add up to the
        whole exactly. Each part is the whole scaled by its weight and rounded
        **down**; the cents that this leaves unassigned go one at a time to the
        parts with the largest discarded remainder, and a tie between equal
        remainders goes to the earlier part. The result therefore never gains
        or loses a cent, and the same input always gives the same parts.

    ``convert_cents``
        The single place a rate is applied. It multiplies, then rounds to the
        nearest whole cent, **half away from zero** — so 1 cent at a rate of
        1.5 becomes 2, and -1 cent becomes -2. Nothing else in the package
        rounds, which is what makes a conversion reproducible.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

_CURRENCY = re.compile(r"[A-Z]{3}$")
_ONE_CENT = Decimal("1")


@dataclass(frozen=True, order=True)
class Money:
    """An integer amount of minor units of one currency."""

    cents: int
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.cents, int):
            raise TypeError(f"cents must be an int, got {type(self.cents).__name__}")
        if not _CURRENCY.match(self.currency):
            raise ValueError(f"currency must be three uppercase letters, got {self.currency!r}")

    def __add__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return Money(self.cents + other.cents, self.currency)

    def __sub__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return Money(self.cents - other.cents, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.cents, self.currency)

    def is_zero(self) -> bool:
        return self.cents == 0

    def _require_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise ValueError(f"cannot combine {self.currency} with {other.currency}")


def allocate(total_cents: int, weights: Sequence[int]) -> list[int]:
    """Share ``total_cents`` over ``weights`` so the parts add up exactly.

    Largest-remainder allocation: every part is first given the exact share
    rounded down, and the cents left over go one each to the parts with the
    largest fractional remainder, earlier parts winning a tie.
    """
    if not weights:
        raise ValueError("cannot allocate over no weights")
    if any(weight < 0 for weight in weights):
        raise ValueError(f"weights cannot be negative, got {list(weights)}")
    total_weight = sum(weights)
    if total_weight == 0:
        raise ValueError("cannot allocate over weights that all sum to zero")

    parts = [total_cents * weight // total_weight for weight in weights]
    leftover = total_cents - sum(parts)
    ordered = sorted(
        range(len(weights)),
        key=lambda index: (-(total_cents * weights[index] % total_weight), index),
    )
    for index in ordered[:leftover]:
        parts[index] += 1
    return parts


def convert_cents(amount_cents: int, rate: Decimal) -> int:
    """Apply ``rate`` to an amount of cents, rounded to the nearest cent.

    Halfway values go away from zero, so a positive half rounds up and a
    negative half rounds down; a ledger that rounded the two directions
    differently would not reconcile against itself.
    """
    if not isinstance(rate, Decimal):
        raise TypeError(f"rate must be a Decimal, got {type(rate).__name__}")
    if rate <= 0:
        raise ValueError(f"rate must be positive, got {rate}")
    scaled = Decimal(amount_cents) * rate
    if amount_cents < 0:
        return -int((-scaled).quantize(_ONE_CENT, rounding=ROUND_HALF_UP))
    return int(scaled.quantize(_ONE_CENT, rounding=ROUND_HALF_UP))
