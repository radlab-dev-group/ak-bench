"""Rate cards and surcharges: what a carrier charges, and what gets added.

A rate card is one carrier's price for one band. A surcharge is something the
carrier adds on top of the line-haul, and the interesting part of a surcharge
is not its amount, it is **what it applies to** and **whether it stacks**.

The line-haul
    ``base_cents + billable_weight * cents_per_kg``, with the multiplication
    rounded once, half away from zero, to the whole cent. Nothing else in the
    line-haul rounds, so a quote can be rebuilt from its parts exactly.

    A card has a ``max_weight_kg``. A parcel whose billable weight is above it
    is not priced by the card at all — not "priced at the maximum", but
    refused — because a carrier that will not take the parcel is not the
    cheapest carrier.

Surcharges
    Each surcharge says three things: *when* it applies (a predicate over the
    shipment and the quote being built), *how much* it is, and *what it is
    computed on*. The base matters and is explicit per surcharge:

    * ``linehaul`` — a percentage of the line-haul only (fuel is this);
    * ``shipment`` — a percentage of the line-haul plus the fixed fees already
      accepted (a peak surcharge is this);
    * ``flat`` — an amount that does not depend on anything.

    A percentage is rounded half away from zero when it is accepted, so the
    total is the sum of already-rounded parts, which is what makes a quote
    auditable line by line.

    Two surcharges in the same ``group`` compete: only the more expensive one
    is accepted and the cheaper is **suppressed** with a reason naming the
    winner. That is how a carrier that charges "heavy parcel" or "oversize",
    never both, is written down. A group with two equal amounts keeps the
    first in declaration order, because "the more expensive one" is not a tie
    breaker and the quote must not depend on the order a dict happened to
    iterate in.

    A surcharge never applies twice: a name appears at most once in a quote,
    and a suppressed one is not a charge.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from freight.errors import UnknownCarrier
from freight.weights import BillableWeight, billable_weight

_ONE_CENT = Decimal("1")
ZERO = Decimal(0)


def round_cents(value: Decimal) -> int:
    """Round an amount of cents to whole cents, half away from zero."""
    return int(value.quantize(_ONE_CENT, rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class RateCard:
    """One carrier's price for one band, and the weight it will still carry."""

    carrier: str
    band: str
    base_cents: int
    cents_per_kg: Decimal
    max_weight_kg: Decimal
    divisor: Decimal = Decimal("5000")
    minimum_kg: Decimal = Decimal("0.5")
    step_kg: Decimal = Decimal("0.5")
    minimum_charge_cents: int = 0

    def __post_init__(self) -> None:
        if self.base_cents < 0:
            raise ValueError(f"base_cents cannot be negative, got {self.base_cents}")
        if self.cents_per_kg < ZERO:
            raise ValueError(f"cents_per_kg cannot be negative, got {self.cents_per_kg}")
        if self.max_weight_kg <= ZERO:
            raise ValueError(f"max_weight_kg must be positive, got {self.max_weight_kg}")
        if self.divisor <= ZERO:
            raise ValueError(f"divisor must be positive, got {self.divisor}")
        if self.step_kg <= ZERO:
            raise ValueError(f"step_kg must be positive, got {self.step_kg}")
        if self.minimum_kg < ZERO:
            raise ValueError(f"minimum_kg cannot be negative, got {self.minimum_kg}")

    def billable_for(self, shipment: Shipment) -> BillableWeight:
        """What this carrier charges for, from its own divisor, minimum and step."""
        return billable_weight(
            shipment.actual_kg,
            shipment.length_cm,
            shipment.width_cm,
            shipment.height_cm,
            divisor=self.divisor,
            minimum_kg=self.minimum_kg,
            step_kg=self.step_kg,
        )

    def carries(self, billable_kg: Decimal) -> bool:
        return billable_kg <= self.max_weight_kg

    def linehaul_cents(self, billable_kg: Decimal) -> int:
        """The line-haul for a billable weight, before any surcharge."""
        raw = Decimal(self.base_cents) + billable_kg * self.cents_per_kg
        return max(round_cents(raw), self.minimum_charge_cents)


@dataclass(frozen=True)
class Shipment:
    """What is being quoted: where, how big, how heavy, and what kind of address."""

    origin: str
    destination: str
    actual_kg: Decimal
    length_cm: Decimal
    width_cm: Decimal
    height_cm: Decimal
    residential: bool = False
    declared_value_cents: int = 0
    on: object = None

    def longest_side_cm(self) -> Decimal:
        return max(self.length_cm, self.width_cm, self.height_cm)

    def is_oversize(self, limit_cm: Decimal) -> bool:
        return self.longest_side_cm() > limit_cm


@dataclass(frozen=True)
class Context:
    """What a surcharge is allowed to look at while deciding."""

    billable_kg: Decimal
    linehaul_cents: int
    fixed_fees_cents: int
    oversize_limit_cm: Decimal

    def accepted_before_percentage(self) -> int:
        return self.linehaul_cents + self.fixed_fees_cents


SurchargePredicate = Callable[[Shipment, Context], bool]


@dataclass(frozen=True)
class Surcharge:
    """One rule about what gets added to a line-haul, and what it is computed on."""

    name: str
    applies: SurchargePredicate
    base: str
    amount_cents: int = 0
    percent: Decimal = ZERO
    group: str | None = None

    def __post_init__(self) -> None:
        if self.base not in ("linehaul", "shipment", "flat"):
            raise ValueError(f"unknown surcharge base: {self.base}")
        if self.base == "flat" and self.percent != ZERO:
            raise ValueError("a flat surcharge cannot carry a percent")
        if self.base != "flat" and self.percent <= ZERO:
            raise ValueError(f"a {self.base} surcharge needs a positive percent")

    def amount_for(self, context: Context) -> int:
        """What this surcharge adds, given what the quote looks like so far."""
        if self.base == "flat":
            return self.amount_cents
        if self.base == "linehaul":
            return round_cents(Decimal(context.linehaul_cents) * self.percent)
        return round_cents(Decimal(context.accepted_before_percentage()) * self.percent)

    def explains_as(self) -> str:
        return f"{self.name} ({self.base})"


@dataclass
class SurchargeBook:
    """The surcharges a quote is built from, in declaration order."""

    surcharges: list[Surcharge] = field(default_factory=list)

    def add(self, surcharge: Surcharge) -> Surcharge:
        self.surcharges.append(surcharge)
        return surcharge

    def names(self) -> list[str]:
        return [surcharge.name for surcharge in self.surcharges]


@dataclass
class RateTable:
    """Every carrier's cards, and the question "can you quote this lane?"."""

    cards: list[RateCard] = field(default_factory=list)

    def add(self, card: RateCard) -> RateCard:
        self.cards.append(card)
        return card

    def card_for(self, carrier: str, band: str) -> RateCard | None:
        for card in self.cards:
            if card.carrier == carrier and card.band == band:
                return card
        return None

    def requires(self, carrier: str) -> RateCard:
        for card in self.cards:
            if card.carrier == carrier:
                return card
        raise UnknownCarrier(carrier)

    def carriers(self) -> list[str]:
        return sorted({card.carrier for card in self.cards})

    def quoteable_carriers(self, band: str) -> list[str]:
        return sorted({card.carrier for card in self.cards if card.band == band})
