"""The refactoring, proven: target structure plus preserved behaviour.

These tests fail on the base commit (the target modules do not exist)
and pass once the pricing is split.
"""

from __future__ import annotations

from billing import price_invoice
from billing.tax import tax_amount
from billing.totals import discount, subtotal


def test_subtotal_sums_the_lines():
    assert subtotal([(1000, 2), (500, 3)]) == 3500
    assert subtotal([]) == 0


def test_discount_threshold_and_rounding():
    assert discount(9_999) == 0
    assert discount(10_000) == 500
    assert discount(10_010) == 501  # 5 % of 10010 = 500.5, half away from zero
    assert discount(0) == 0


def test_tax_amount_rounding():
    assert tax_amount(9500) == 2185
    assert tax_amount(0) == 0
    assert tax_amount(100) == 23


def test_price_invoice_behaviour_is_unchanged():
    assert price_invoice([(1000, 2)]) == {
        "subtotal": 2000,
        "discount": 0,
        "tax": 460,
        "total": 2460,
    }
    assert price_invoice([(10_000, 1)]) == {
        "subtotal": 10_000,
        "discount": 500,
        "tax": 2185,
        "total": 11_685,
    }
    assert price_invoice([]) == {"subtotal": 0, "discount": 0, "tax": 0, "total": 0}
