"""A rate book converts with the rate that was in force; one rate is the simple case."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from ledgerlite.errors import MissingRate
from ledgerlite.fx import RateBook
from ledgerlite.money import Money

BOOK = RateBook("EUR")
BOOK.publish("USD", Decimal("0.90"), datetime(2026, 1, 1, tzinfo=UTC))


def a_book() -> RateBook:
    return RateBook("EUR")


def test_a_foreign_amount_is_valued_at_the_published_rate():
    book = a_book()
    book.publish("USD", Decimal("0.90"), datetime(2026, 1, 1, tzinfo=UTC))
    converted = book.convert(Money(10_000, "USD"), "EUR", datetime(2026, 6, 1, tzinfo=UTC))
    assert converted.target == Money(9_000, "EUR")


def test_the_home_currency_is_worth_exactly_itself():
    book = a_book()
    converted = book.convert(Money(500, "EUR"), "EUR", datetime(2026, 6, 1, tzinfo=UTC))
    assert converted.target == Money(500, "EUR")


def test_home_to_foreign_divides_by_the_rate():
    book = a_book()
    book.publish("USD", Decimal("0.90"), datetime(2026, 1, 1, tzinfo=UTC))
    converted = book.convert(Money(9_000, "EUR"), "USD", datetime(2026, 6, 1, tzinfo=UTC))
    assert converted.target == Money(10_000, "USD")


def test_a_moment_before_the_first_publication_has_no_answer():
    book = a_book()
    book.publish("USD", Decimal("0.90"), datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(MissingRate):
        book.convert(Money(100, "USD"), "EUR", datetime(2025, 12, 31, tzinfo=UTC))


def test_the_rate_that_answered_is_reported_with_the_amount():
    book = a_book()
    book.publish("USD", Decimal("0.90"), datetime(2026, 1, 1, tzinfo=UTC))
    converted = book.convert(Money(1_000, "USD"), "EUR", datetime(2026, 6, 1, tzinfo=UTC))
    assert converted.rate == Decimal("0.90")
