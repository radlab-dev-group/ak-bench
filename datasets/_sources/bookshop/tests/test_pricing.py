"""The suite the repository ships with: the rules away from their edges.

Deliberately, no subtotal here sits exactly on a tier threshold. The benchmark
task owns the boundary cases, and a fixture that tested them would hand the
answer to the agent it is meant to examine.
"""

from bookshop.pricing import Line, discount_tier, price_basket, round_cents, split_amount
from decimal import Decimal


def test_a_small_basket_pays_no_discount():
    basket = price_basket([Line("DBP", 2, 4900)])
    assert basket.subtotal_cents == 9800
    assert basket.discount_cents == 0
    assert basket.tier is None


def test_a_larger_basket_earns_the_ten_percent_tier():
    lines = [Line("PRA", 7, 9900)]
    basket = price_basket(lines)
    assert basket.subtotal_cents == 69300
    assert basket.tier == Decimal("0.10")
    assert basket.discount_cents == 6930


def test_tax_is_added_after_the_discount():
    basket = price_basket([Line("CLN", 2, 3950)])
    assert basket.taxable_cents == 7900
    assert basket.tax_cents == round_cents(Decimal(7900) * Decimal("0.23"))
    assert basket.total_cents == basket.taxable_cents + basket.tax_cents


def test_a_voucher_never_removes_more_than_is_left():
    basket = price_basket([Line("TST", 1, 2499)], voucher_cents=99999)
    assert basket.voucher_cents == 2499
    assert basket.taxable_cents == 0
    assert basket.total_cents == 0


def test_a_line_total_is_exact_multiplication():
    assert Line("DBP", 3, 1999).total_cents == 5997


def test_the_tier_looks_at_the_untouched_subtotal():
    assert discount_tier(9999) == (None, 0)
    assert discount_tier(12000)[0] == Decimal("0.05")


def test_a_split_adds_up_to_the_amount():
    assert sum(split_amount(1000, 3)) == 1000
    assert split_amount(1000, 3) == [334, 333, 333]


def test_round_cents_moves_away_from_zero_on_a_half():
    assert round_cents(Decimal("1234.5")) == 1235
    assert round_cents(Decimal("1234.4")) == 1234
