"""A lot is what it holds, and it is usable until the day after its expiry."""

from datetime import date

import pytest
from stockpile.lots import Lot


def a_lot(quantity: int = 100, reserved: int = 0) -> Lot:
    return Lot(
        lot_id="L1",
        sku="YOG",
        warehouse="W1",
        quantity=quantity,
        reserved=reserved,
        received_on=date(2026, 1, 1),
        expires_on=date(2026, 6, 1),
    )


def test_free_is_what_is_left_after_reservations():
    assert a_lot(100, 30).free() == 70


def test_a_lot_expires_the_day_after_its_expiry_date():
    lot = a_lot()
    assert not lot.is_expired(date(2026, 6, 1))
    assert lot.is_expired(date(2026, 6, 2))


def test_a_fully_reserved_lot_is_still_there_but_not_useable():
    lot = a_lot(50, 50)
    assert lot.free() == 0
    assert not lot.useable(date(2026, 5, 1))


def test_an_expired_lot_is_never_useable():
    assert not a_lot().useable(date(2026, 7, 1))


def test_a_reservation_larger_than_the_lot_is_refused():
    with pytest.raises(ValueError):
        a_lot(10, 20)
