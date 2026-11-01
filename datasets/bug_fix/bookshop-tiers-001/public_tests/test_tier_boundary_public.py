"""What a developer is told about this defect: the boundary is inclusive.

These tests are visible to the agent. They state the rule and probe it at the
edges the hidden tests also care about, so an agent can find the defect without
being handed the exact assertions the evaluation uses.
"""

from decimal import Decimal

from bookshop.pricing import Line, discount_tier, price_basket


def test_below_the_first_threshold_no_tier_is_earned():
    assert discount_tier(9_999) == (None, 0)


def test_the_first_threshold_is_reached_at_its_own_value():
    assert discount_tier(10_000) == (Decimal("0.05"), 10_000)


def test_a_basket_at_the_threshold_is_discounted():
    basket = price_basket([Line("DBP", 1, 10_000)])
    assert basket.subtotal_cents == 10_000
    assert basket.tier == Decimal("0.05")
    assert basket.discount_cents == 500


def test_the_highest_applicable_tier_wins():
    assert discount_tier(200_000)[0] == Decimal("0.15")
    assert discount_tier(50_000)[0] == Decimal("0.10")
