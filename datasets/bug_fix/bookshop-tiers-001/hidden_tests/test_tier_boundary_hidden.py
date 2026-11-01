"""The defect, proven from every side the mutation can hide behind.

The hidden tests pass on the base commit and fail once the mutation is applied;
that is the contract of a bug-fix task (docs/DATASETS.md). They cover each
threshold, the value one cent below it, and the cent immediately above, so an
agent cannot pass by special-casing one number.
"""

from decimal import Decimal

from bookshop.pricing import Line, discount_tier, price_basket


def test_no_tier_one_cent_below_the_threshold():
    assert discount_tier(9_999) == (None, 0)
    assert discount_tier(49_999) == (Decimal("0.05"), 10_000)


def test_the_first_threshold_is_inclusive():
    assert discount_tier(10_000) == (Decimal("0.05"), 10_000)
    assert discount_tier(10_001) == (Decimal("0.05"), 10_000)


def test_the_second_threshold_is_inclusive():
    assert discount_tier(50_000) == (Decimal("0.10"), 50_000)
    assert discount_tier(50_001) == (Decimal("0.10"), 50_000)


def test_the_third_threshold_is_inclusive():
    assert discount_tier(200_000) == (Decimal("0.15"), 200_000)
    assert discount_tier(200_001) == (Decimal("0.15"), 200_000)


def test_a_basket_at_exactly_ten_thousand_earns_five_percent():
    basket = price_basket([Line("PRA", 1, 10_000)])
    assert basket.tier == Decimal("0.05")
    assert basket.discount_cents == 500
    assert basket.taxable_cents == 9_500
    assert basket.total_cents == 9_500 + basket.tax_cents


def test_a_basket_at_exactly_fifty_thousand_earns_ten_percent():
    basket = price_basket([Line("PRA", 5, 10_000)])
    assert basket.tier == Decimal("0.10")
    assert basket.discount_cents == 5_000
    assert basket.taxable_cents == 45_000


def test_a_basket_at_exactly_two_hundred_thousand_earns_fifteen_percent():
    basket = price_basket([Line("PRA", 20, 10_000)])
    assert basket.tier == Decimal("0.15")
    assert basket.discount_cents == 30_000
    assert basket.taxable_cents == 170_000


def test_one_cent_over_a_threshold_uses_the_same_tier():
    at = price_basket([Line("PRA", 1, 10_000)])
    over = price_basket([Line("PRA", 1, 10_001)])
    assert at.tier == over.tier == Decimal("0.05")
    assert over.discount_cents == 500


def test_a_voucher_still_applies_after_the_threshold_discount():
    basket = price_basket([Line("PRA", 1, 10_000)], voucher_cents=1_000)
    assert basket.discount_cents == 500
    assert basket.voucher_cents == 1_000
    assert basket.taxable_cents == 8_500


def test_the_tax_is_computed_on_the_discounted_amount_at_the_threshold():
    basket = price_basket([Line("PRA", 2, 5_000)])
    assert basket.taxable_cents == 9_500
    assert basket.tax_cents == 2_185  # 23 % of 9 500, half away from zero
    assert basket.total_cents == 11_685
