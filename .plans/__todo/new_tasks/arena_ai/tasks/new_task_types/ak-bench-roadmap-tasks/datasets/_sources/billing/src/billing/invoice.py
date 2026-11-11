"""Pricing an invoice.

``price_invoice(lines)`` takes ``(unit_price_cents, quantity)`` pairs
and returns a dict with ``subtotal``, ``discount``, ``tax`` and
``total`` in cents. A subtotal of 10 000 cents or more earns a 5 %
discount; tax is 23 % of the discounted amount, rounded half away
from zero to the nearest cent.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def price_invoice(lines: list[tuple[int, int]]) -> dict:
    """Price the invoice under the rules above."""
    subtotal = 0
    for unit_price, quantity in lines:
        subtotal += unit_price * quantity
    if subtotal >= 10_000:
        discount = int(
            (Decimal(subtotal) * Decimal("0.05")).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    else:
        discount = 0
    taxable = subtotal - discount
    tax = int(
        (Decimal(taxable) * Decimal("0.23")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    total = taxable + tax
    return {"subtotal": subtotal, "discount": discount, "tax": tax, "total": total}
