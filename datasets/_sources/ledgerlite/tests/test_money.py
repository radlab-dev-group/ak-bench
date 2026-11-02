"""Money is exact, and an allocation never gains or loses a cent."""

from decimal import Decimal

import pytest
from ledgerlite.money import Money, allocate, convert_cents


def test_amounts_of_one_currency_add():
    assert Money(150, "EUR") + Money(45, "EUR") == Money(195, "EUR")


def test_adding_two_currencies_is_refused():
    with pytest.raises(ValueError):
        Money(100, "EUR") + Money(100, "USD")


def test_an_allocation_adds_up_to_the_whole():
    parts = allocate(100, [1, 1, 1])
    assert sum(parts) == 100


def test_the_leftover_cents_go_to_the_earliest_parts():
    assert allocate(10, [1, 1, 1]) == [4, 3, 3]


def test_a_weight_of_zero_gets_nothing():
    assert allocate(99, [0, 1]) == [0, 99]


def test_a_negative_amount_is_allocated_without_losing_a_cent():
    assert sum(allocate(-100, [1, 1, 1])) == -100


def test_conversion_rounds_half_away_from_zero():
    assert convert_cents(100, Decimal("1.5")) == 150
    assert convert_cents(-100, Decimal("1.5")) == -150


def test_a_rate_of_one_is_the_identity():
    assert convert_cents(1234, Decimal(1)) == 1234
