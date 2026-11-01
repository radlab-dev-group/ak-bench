"""Basket pricing: tiers, tax and the rounding rules that go with them.

The rules, in the order they are applied:

1. A line total is ``unit_price_cents * quantity``, exact, no rounding.
2. The basket subtotal is the sum of the line totals.
3. A tier discount is taken from the subtotal. The tier is chosen by the
   subtotal *before* the discount: 5 % from 10 000 cents, 10 % from 50 000
   cents, 15 % from 200 000 cents. A subtotal of exactly 10 000 cents earns 5 %,
   the threshold is inclusive.
4. A voucher is applied to the discounted subtotal, never below zero, and never
   removes more than the voucher's own cent amount.
5. Tax is added last, on the amount after discount and voucher, and it is the
   only place where rounding happens: half away from zero, to the nearest cent.
6. ``split_amount`` shares an amount between parties so that the parts add up to
   the whole exactly; the remainder goes to the earliest parties, one cent each.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

#: (inclusive subtotal threshold in cents, discount as a fraction of the subtotal)
TIERS: tuple[tuple[int, Decimal], ...] = (
    (200_000, Decimal("0.15")),
    (50_000, Decimal("0.10")),
    (10_000, Decimal("0.05")),
)

TAX_RATE = Decimal("0.23")


@dataclass(frozen=True)
class Line:
    """One ordered item: how many, and at what unit price."""

    sku: str
    quantity: int
    unit_price_cents: int

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity}")
        if self.unit_price_cents < 0:
            raise ValueError(f"unit price cannot be negative, got {self.unit_price_cents}")

    @property
    def total_cents(self) -> int:
        return self.quantity * self.unit_price_cents


@dataclass(frozen=True)
class Basket:
    """The priced result: every number is in cents, every rule is visible."""

    subtotal_cents: int
    discount_cents: int
    voucher_cents: int
    taxable_cents: int
    tax_cents: int
    total_cents: int
    tier: Decimal | None = field(default=None)


def discount_tier(subtotal_cents: int) -> tuple[Decimal | None, int]:
    """The tier a subtotal earns: ``(fraction, threshold)`` or ``(None, 0)``."""
    for threshold, fraction in TIERS:
        if subtotal_cents >= threshold:
            return fraction, threshold
    return None, 0


def round_cents(value: Decimal) -> int:
    """Round a decimal amount of cents to whole cents, half away from zero."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def price_basket(lines: list[Line], voucher_cents: int = 0) -> Basket:
    """Price a basket under the rules stated in the module docstring."""
    if voucher_cents < 0:
        raise ValueError(f"voucher cannot be negative, got {voucher_cents}")

    subtotal = sum(line.total_cents for line in lines)
    fraction, _threshold = discount_tier(subtotal)
    discount = round_cents(Decimal(subtotal) * fraction) if fraction else 0

    after_discount = subtotal - discount
    voucher = min(voucher_cents, after_discount)
    taxable = after_discount - voucher

    tax = round_cents(Decimal(taxable) * TAX_RATE)
    return Basket(
        subtotal_cents=subtotal,
        discount_cents=discount,
        voucher_cents=voucher,
        taxable_cents=taxable,
        tax_cents=tax,
        total_cents=taxable + tax,
        tier=fraction,
    )


def split_amount(amount_cents: int, parties: int) -> list[int]:
    """Split an amount so the parts add up exactly; the remainder goes first."""
    if parties <= 0:
        raise ValueError(f"parties must be positive, got {parties}")
    base, remainder = divmod(amount_cents, parties)
    return [base + 1 if index < remainder else base for index in range(parties)]
