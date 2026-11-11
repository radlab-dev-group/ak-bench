"""The target structure, in miniature: helpers exist and pricing holds."""

from __future__ import annotations

from billing import price_invoice
from billing.tax import tax_amount
from billing.totals import discount, subtotal


def test_the_helpers_compute_the_same_numbers():
    assert subtotal([(1000, 2)]) == 2000
    assert discount(10_000) == 500
    assert tax_amount(9500) == 2185


def test_price_invoice_still_works():
    assert price_invoice([(1000, 2)])["total"] == 2460
