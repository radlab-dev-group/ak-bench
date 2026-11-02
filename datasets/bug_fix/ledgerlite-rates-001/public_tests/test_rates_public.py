"""The invariants a developer can be told about, without the exact cases."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from ledgerlite.errors import MissingRate
from ledgerlite.fx import RateBook
from ledgerlite.money import Money


def a_book() -> RateBook:
    return RateBook("EUR")


def test_a_conversion_uses_the_published_rate():
    book = a_book()
    book.publish("USD", Decimal("0.90"), datetime(2026, 1, 1, tzinfo=UTC))
    converted = book.convert(Money(10_000, "USD"), "EUR", datetime(2026, 6, 1, tzinfo=UTC))
    assert converted.target == Money(9_000, "EUR")


def test_the_home_currency_needs_no_rate():
    book = a_book()
    converted = book.convert(Money(123, "EUR"), "EUR", datetime(2026, 6, 1, tzinfo=UTC))
    assert converted.target == Money(123, "EUR")


def test_a_moment_before_the_first_publication_is_refused():
    book = a_book()
    book.publish("USD", Decimal("0.90"), datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(MissingRate):
        book.convert(Money(100, "USD"), "EUR", datetime(2025, 6, 1, tzinfo=UTC))
