"""The finished part of the fixture: pricing behaviour.

These tests pin the behaviour the refactoring must preserve.
"""

from __future__ import annotations

from billing import price_invoice


def test_a_small_invoice_has_no_discount():
    assert price_invoice([(1000, 2)]) == {
        "subtotal": 2000,
        "discount": 0,
        "tax": 460,
        "total": 2460,
    }


def test_a_large_invoice_earns_the_discount():
    result = price_invoice([(10_000, 1)])
    assert result["subtotal"] == 10_000
    assert result["discount"] == 500
    assert result["tax"] == 2185
    assert result["total"] == 11_685


def test_an_empty_invoice_is_zero():
    assert price_invoice([]) == {"subtotal": 0, "discount": 0, "tax": 0, "total": 0}
