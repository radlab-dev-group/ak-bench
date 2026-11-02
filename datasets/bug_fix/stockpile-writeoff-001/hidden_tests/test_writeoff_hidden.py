"""The rule the defect breaks: a write-off removes only what is free.

Every test here puts a claim on a lot that has since expired and asks what the
write-off did to it. The question is always the same afterwards: does the
claim still correspond to something the warehouse can actually commit?
"""

from datetime import date

import pytest
from stockpile.errors import NotEnoughReserved
from stockpile.lots import Lot
from stockpile.stock import Reservation, Stock

NOW = date(2026, 5, 10)
GONE = date(2026, 4, 1)


def a_stock(*lots: Lot) -> Stock:
    stock = Stock()
    for lot in lots:
        stock.receive(lot)
    return stock


def a_lot(
    lot_id: str = "L1",
    quantity: int = 100,
    expires: date = GONE,
    received: date = date(2026, 1, 1),
) -> Lot:
    return Lot(
        lot_id=lot_id,
        sku="YOG",
        warehouse="W1",
        quantity=quantity,
        received_on=received,
        expires_on=expires,
    )


def hold(stock: Stock, lot_id: str, quantity: int, reservation_id: str = "R1") -> None:
    stock.reserve(
        Reservation(
            reservation_id=reservation_id,
            holder="shop",
            sku="YOG",
            warehouse="W1",
            lots=((lot_id, quantity),),
        ),
        on=NOW,
    )


def test_the_reserved_part_of_an_expired_lot_survives_a_write_off():
    stock = a_stock(a_lot(quantity=100))
    hold(stock, "L1", 40)
    stock.write_off_expired(now=NOW)
    assert stock.lot("L1").quantity == 40
    assert stock.lot("L1").reserved == 40
    assert stock.available("YOG", now=NOW) == 0
    assert stock.on_hand("YOG") == 40


def test_a_claim_on_an_expired_lot_can_still_be_committed_after_a_write_off():
    stock = a_stock(a_lot(quantity=100))
    hold(stock, "L1", 40)
    stock.write_off_expired(now=NOW)
    stock.commit("R1", 40, on=NOW)
    assert stock.on_hand("YOG") == 0
    assert stock.reservation("R1").held() == 0


def test_the_write_off_still_removes_the_free_part():
    stock = a_stock(a_lot(quantity=100))
    hold(stock, "L1", 30)
    stock.write_off_expired(now=NOW)
    assert stock.lot("L1").quantity == 30
    movements = [m for m in stock.movements() if m.caused_by == "write-off"]
    assert movements and movements[-1].quantity == 70


def test_a_fully_reserved_expired_lot_is_not_written_off_at_all():
    stock = a_stock(a_lot(quantity=50))
    hold(stock, "L1", 50)
    assert stock.write_off_expired(now=NOW) == []
    assert stock.on_hand("YOG") == 50


def test_two_expired_lots_are_each_written_off_against_their_own_reservations():
    stock = a_stock(
        a_lot("L1", quantity=100),
        a_lot("L2", quantity=80),
    )
    hold(stock, "L1", 30, "R1")
    hold(stock, "L2", 80, "R2")
    assert stock.write_off_expired(now=NOW) == ["L1"]
    assert stock.lot("L1").quantity == 30
    assert stock.lot("L2").quantity == 80
    assert stock.lot("L2").reserved == 80


def test_a_committed_claim_and_a_reserved_claim_are_both_untouched():
    stock = a_stock(a_lot(quantity=100))
    hold(stock, "L1", 60)
    stock.commit("R1", 30, on=NOW)
    stock.write_off_expired(now=NOW)
    assert stock.lot("L1").quantity == 30
    assert stock.lot("L1").reserved == 30
    stock.commit("R1", 30, on=NOW)
    assert stock.on_hand("YOG") == 0


def test_a_release_after_a_write_off_never_gives_back_destroyed_stock():
    stock = a_stock(a_lot(quantity=100))
    hold(stock, "L1", 40)
    stock.write_off_expired(now=NOW)
    stock.release("R1", on=NOW)
    assert stock.lot("L1").reserved == 0
    # The released unit is on the shelf, but the lot is expired, so it is
    # not available and not useable: it is stock that has to be written off,
    # never stock that gets sold.
    assert stock.lot("L1").free() == 40
    assert stock.available("YOG", now=NOW) == 0
    assert not stock.lot("L1").useable(NOW)
    assert stock.on_hand("YOG") == 40
    with pytest.raises(NotEnoughReserved):
        stock.commit("R1", 1, on=NOW)
