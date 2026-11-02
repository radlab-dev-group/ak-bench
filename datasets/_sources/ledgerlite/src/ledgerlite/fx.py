"""Converting an amount as of a moment, from a book of published rates.

A rate says what one unit of a foreign currency is worth in the ledger's home
currency, and it is **in force from the instant it was published until the next
one is**. A conversion therefore always answers a second question besides
"how much": *as of when*. This is the rule that keeps a ledger honest about the
past — a conversion of an invoice booked in March must use March's rate, even
though the book has moved on since.

The rules
    * A rate is published for one currency, against the home currency, with an
      effective-from instant. Rates never expire and are never edited.
    * ``rate_for(currency, at)`` returns the rate with the **latest**
      ``effective_from`` that is still **at or before** ``at``. A rate that is
      published in the future is not a rate the ledger could have known, so it
      is never selected; asking for a moment before the first published rate
      raises :class:`~ledgerlite.errors.MissingRate`.
    * The home currency is worth exactly itself: converting it is an identity
      and needs no rate at all.
    * A conversion between two foreign currencies goes through the home
      currency, and rounds once — at the end, with the rule in
      :func:`~ledgerlite.money.convert_cents`. Rounding twice would let the same
      amount take two different values depending on how the path was written.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from ledgerlite.errors import MissingRate
from ledgerlite.money import Money, convert_cents

#: Exact by definition, so the home currency never needs a published rate.
HOME_UNIT = Decimal(1)


@dataclass(frozen=True, order=True)
class Rate:
    """What one unit of ``currency`` is worth in the home currency, from one instant."""

    effective_from: datetime
    currency: str
    per_unit: Decimal

    def __post_init__(self) -> None:
        if self.per_unit <= 0:
            raise ValueError(f"a rate must be positive, got {self.per_unit}")

    def value_of(self, cents: int) -> int:
        """The home-currency value of an amount of this currency."""
        return convert_cents(cents, self.per_unit)

    def before(self, moment: datetime) -> bool:
        """Whether this rate is already in force at ``moment``."""
        return self.effective_from <= moment


@dataclass(frozen=True)
class Conversion:
    """The answer to one conversion: the amount, and the rate that produced it."""

    source: Money
    target: Money
    rate: Decimal

    def at_least(self, cents: int) -> bool:
        return self.target.cents >= cents


class RateBook:
    """Published rates, and the only question that matters: what was in force then?"""

    def __init__(self, home_currency: str = "EUR") -> None:
        self.home_currency = home_currency
        self._rates: list[Rate] = []

    def publish(self, currency: str, per_unit: Decimal, effective_from: datetime) -> Rate:
        """Publish a rate; it is in force from ``effective_from`` until a later one."""
        rate = Rate(effective_from=effective_from, currency=currency, per_unit=per_unit)
        self._rates.append(rate)
        self._rates.sort(key=lambda item: (item.effective_from, item.currency))
        return rate

    def rates(self, currency: str | None = None) -> list[Rate]:
        """Every published rate for a currency, oldest first."""
        if currency is None:
            return list(self._rates)
        return [rate for rate in self._rates if rate.currency == currency]

    def rate_for(self, currency: str, at: datetime) -> Rate:
        """The rate of ``currency`` in force at ``at``.

        The rate published most recently at or before ``at`` wins. A future
        publication is not knowledge, so it is never the answer; there is no
        answer at all before the first publication.
        """
        in_force = [rate for rate in self._rates if rate.currency == currency and rate.before(at)]
        if not in_force:
            raise MissingRate(currency, at)
        return in_force[-1]

    def convert(self, money: Money, to_currency: str, at: datetime) -> Conversion:
        """Convert ``money`` into ``to_currency``, using the rates in force at ``at``.

        Same-currency is an identity. Foreign to home multiplies by that
        currency's rate; home to foreign divides by it. Two foreign currencies
        go foreign → home → foreign and round once, at the end.
        """
        if money.currency == to_currency:
            return Conversion(source=money, target=money, rate=HOME_UNIT)

        if money.currency == self.home_currency:
            inverse = HOME_UNIT / self.rate_for(to_currency, at).per_unit
            cents = convert_cents(money.cents, inverse)
            return Conversion(source=money, target=Money(cents, to_currency), rate=inverse)

        rate = self.rate_for(money.currency, at)
        if to_currency == self.home_currency:
            cents = rate.value_of(money.cents)
            return Conversion(source=money, target=Money(cents, to_currency), rate=rate.per_unit)

        other = self.rate_for(to_currency, at)
        combined = rate.per_unit / other.per_unit
        cents = convert_cents(money.cents, combined)
        return Conversion(source=money, target=Money(cents, to_currency), rate=combined)

    def restate(self, entries: list[tuple[Money, datetime]], at: datetime) -> Money:
        """Value a list of ``(amount, as-of)`` pairs at one moment and add them up."""
        total = Money(0, self.home_currency)
        for money, moment in entries:
            total = total + self.convert(money, self.home_currency, moment).target
        return total
