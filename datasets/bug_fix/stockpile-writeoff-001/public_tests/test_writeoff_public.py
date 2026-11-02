"""The invariant a developer can be told about, without the exact cases."""

from datetime import date

from stockpile.lots import Lot
from stockpile.stock import Stock


def a_stock(lot: Lot) -> Stock:
    stock = Stock()
    stock.receive(lot)
    return stock


def a_lot(quantity: int, expires: date, lot_id: str = "L1") -> Lot:
    return Lot(
        lot_id=lot_id,
        sku="YOG",
        warehouse="W1",
        quantity=quantity,
        received_on=date(2026, 1, 1),
        expires_on=expires,
    )


def test_an_expired_lot_with_no_claims_is_written_off():
    stock = a_stock(a_lot(100, date(2026, 4, 1)))
    assert stock.write_off_expired(now=date(2026, 5, 10)) == ["L1"]
    assert stock.on_hand("YOG") == 0


def test_a_live_lot_is_not_written_off():
    stock = a_stock(a_lot(100, date(2026, 6, 1)))
    assert stock.write_off_expired(now=date(2026, 5, 10)) == []
    assert stock.on_hand("YOG") == 100
