"""The as-of contract: the rate in force is the latest one published by the moment.

Every test here publishes a currency at least twice, which is the one situation
the repository suite never reaches. The question is always the same: given a
moment, which of the published rates does the book answer with?
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from ledgerlite.errors import MissingRate
from ledgerlite.fx import RateBook
from ledgerlite.money import Money

EUR = "EUR"


def a_book() -> RateBook:
    return RateBook(EUR)


def at(day: int) -> datetime:
    return datetime(2026, 5, day, tzinfo=UTC)


def test_a_revision_changes_the_answer_from_that_instant_on():
    book = a_book()
    book.publish("USD", Decimal("0.90"), at(1))
    book.publish("USD", Decimal("0.80"), at(10))
    before = book.convert(Money(10_000, "USD"), EUR, at(9))
    after = book.convert(Money(10_000, "USD"), EUR, at(10))
    assert before.target == Money(9_000, EUR)
    assert after.target == Money(8_000, EUR)


def test_a_moment_exactly_at_the_revision_uses_the_new_rate():
    book = a_book()
    book.publish("USD", Decimal("0.90"), at(1))
    book.publish("USD", Decimal("0.80"), at(10))
    assert book.convert(Money(10_000, "USD"), EUR, at(10)).target == Money(8_000, EUR)


def test_the_answer_just_before_the_revision_uses_the_old_rate():
    book = a_book()
    book.publish("USD", Decimal("0.90"), at(1))
    book.publish("USD", Decimal("0.80"), at(10))
    assert book.convert(Money(10_000, "USD"), EUR, at(9)).target == Money(9_000, EUR)


def test_three_revisions_pick_the_newest_at_or_before_the_moment():
    book = a_book()
    book.publish("USD", Decimal("1.00"), at(1))
    book.publish("USD", Decimal("0.90"), at(10))
    book.publish("USD", Decimal("0.80"), at(20))
    assert book.convert(Money(1_000, "USD"), EUR, at(15)).target == Money(900, EUR)
    assert book.convert(Money(1_000, "USD"), EUR, at(20)).target == Money(800, EUR)


def test_a_future_publication_never_shadows_the_past():
    book = a_book()
    book.publish("USD", Decimal("0.90"), at(10))
    book.publish("USD", Decimal("0.80"), at(30))
    assert book.convert(Money(10_000, "USD"), EUR, at(20)).target == Money(9_000, EUR)


def test_rates_of_other_currencies_do_not_interfere():
    book = a_book()
    book.publish("USD", Decimal("0.90"), at(1))
    book.publish("USD", Decimal("0.80"), at(10))
    book.publish("GBP", Decimal("0.85"), at(1))
    assert book.convert(Money(100, "GBP"), EUR, at(20)).target == Money(85, EUR)
    assert book.convert(Money(10_000, "USD"), EUR, at(20)).target == Money(8_000, EUR)


def test_home_to_foreign_divides_by_the_newest_rate():
    book = a_book()
    book.publish("USD", Decimal("0.90"), at(1))
    book.publish("USD", Decimal("0.80"), at(10))
    assert book.convert(Money(800, EUR), "USD", at(15)).target == Money(1000, "USD")
    assert book.convert(Money(800, EUR), "USD", at(5)).target == Money(889, "USD")


def test_a_foreign_pair_conversion_uses_the_newest_of_both():
    book = a_book()
    book.publish("USD", Decimal("0.90"), at(1))
    book.publish("USD", Decimal("0.80"), at(10))
    book.publish("GBP", Decimal("0.80"), at(1))
    book.publish("GBP", Decimal("0.75"), at(12))
    assert book.convert(Money(10_000, "USD"), "GBP", at(15)).target == Money(10_667, "GBP")


def test_restate_uses_the_rate_in_force_at_each_moment():
    book = a_book()
    book.publish("USD", Decimal("0.90"), at(1))
    book.publish("USD", Decimal("0.80"), at(10))
    total = book.restate([(Money(10_000, "USD"), at(5)), (Money(10_000, "USD"), at(15))], at(31))
    assert total == Money(17_000, EUR)


def test_a_moment_before_the_first_publication_is_still_refused():
    book = a_book()
    book.publish("USD", Decimal("0.90"), at(10))
    book.publish("USD", Decimal("0.80"), at(20))
    with pytest.raises(MissingRate):
        book.rate_for("USD", at(5))
