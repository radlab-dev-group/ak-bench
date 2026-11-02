"""Rate shopping: which carrier should take the parcel. The rules are this docstring.

``shop(shipment, *, zones, rates, surcharges, divisor, minimum_kg, step_kg)``
quotes every carrier that can be asked, and returns a :class:`ShoppingResult`
with the cheapest quote and the reason every other carrier was not it. It is a
pure function: nothing is booked, the shipment is read and never modified, and
calling it twice with the same arguments returns the same result.

Who gets quoted
    Every carrier that holds a card for the **band** of the lane, which is
    ``zones.band_between(shipment.origin, shipment.destination)``. A carrier
    with no card for the band is not asked, and is reported as
    ``"no card for <band>"``. A lane that is not routable at all is not a
    shopping result but an exception, because there is nothing to compare.

    The billable weight is computed **per carrier**, from the carrier's own
    divisor, minimum and step — see :mod:`freight.weights` — because two
    carriers can disagree about what a parcel weighs, and that disagreement is
    sometimes the whole answer.

What a quote costs
    The line-haul comes from the card. Surcharges then run **in declaration
    order**, and each one decides against the quote as it looks at that moment:
    a percentage of the line-haul sees only the line-haul, a percentage of the
    shipment sees the line-haul plus the fixed fees accepted before it, and a
    flat amount sees nothing. A surcharge whose predicate is false is not
    charged and is not reported; it simply does not apply.

    Two surcharges in the same group compete for the same slot and only the
    more expensive is charged, the cheaper being suppressed with a reason that
    names the winner; equal amounts keep the one declared first. A suppressed
    surcharge is never part of ``total_cents``.

    A card refuses a parcel whose billable weight is above its
    ``max_weight_kg``: that is ``"too heavy for the card"``, not a price.

The result
    ``best`` is the quote with the lowest ``total_cents``. A tie is broken by
    the lower billable weight, and a tie still unbroken by the carrier name in
    alphabetical order — the answer must not depend on the order the cards
    happen to be stored in. ``quotes`` holds every quote that was made,
    cheapest first, ordered the same way ``best`` was chosen. ``rejected``
    holds one :class:`Rejection` per carrier that was not quoted or not priced,
    ordered by carrier name, each with the reason it was refused.

    A shopping run in which no carrier produced a price is not an empty result:
    it raises :class:`~freight.errors.NoQuotableCarrier`, because "the cheapest
    is nothing" is not an answer a caller can act on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from freight.pricing import RateTable, Shipment, SurchargeBook
from freight.zones import ZoneTable

#: The side a parcel may not exceed before the oversize rules start to apply.
OVERSIZE_LIMIT_CM = Decimal("120")


@dataclass(frozen=True)
class SurchargeLine:
    """One surcharge that was charged, with what it was computed on."""

    name: str
    cents: int
    base: str


@dataclass(frozen=True)
class Suppressed:
    """One surcharge that lost its group and was therefore not charged."""

    name: str
    lost_to: str


@dataclass(frozen=True)
class Quote:
    """One carrier's price for the shipment, with its working shown."""

    carrier: str
    band: str
    billable_kg: object
    basis: str
    linehaul_cents: int
    surcharges: tuple[SurchargeLine, ...] = ()
    suppressed: tuple[Suppressed, ...] = ()
    total_cents: int = 0

    def surcharge_cents(self) -> int:
        return sum(line.cents for line in self.surcharges)


@dataclass(frozen=True)
class Rejection:
    """A carrier that did not produce a price, and why."""

    carrier: str
    reason: str


@dataclass
class ShoppingResult:
    """The whole answer: the best quote, every quote, and every refusal."""

    best: Quote | None = None
    quotes: list[Quote] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)

    def carriers_quoted(self) -> list[str]:
        return [quote.carrier for quote in self.quotes]

    def total_for(self, carrier: str) -> int:
        for quote in self.quotes:
            if quote.carrier == carrier:
                return quote.total_cents
        raise KeyError(carrier)


def shop(
    shipment: Shipment,
    *,
    zones: ZoneTable,
    rates: RateTable,
    surcharges: SurchargeBook,
) -> ShoppingResult:
    """Quote every carrier that can take ``shipment`` and pick the cheapest."""
    raise NotImplementedError("shop is specified in this module and not yet written")
