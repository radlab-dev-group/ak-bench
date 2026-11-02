"""Reserving is not taking; committing is."""

from datetime import date

import pytest
from stockpile.errors import (
    ExpiredLot,
    InsufficientStock,
    NotEnoughReserved,
    ReservationNotHeld,
)
from stockpile.lots import Lot
from stockpile.stock import Reservation, Stock

DAY = date(2026, 5, 10)


def a_stock(*lots: Lot) -> Stock:
    stock = Stock()
    for lot in lots:
        stock.receive(Lot(
            lot_id=lot.lot_id,
            sku=lot.sku,
            warehouse=lot.warehouse,
            quantity=lot.quantity,
            received_on=lot.received_on,
            expires_on=lot.expires_on,
            reserved=lot.reserved,
        ))
    return stock


def a_lot(quantity: int = 100, lot_id: str = "L1", expires: date = date(2026, 6, 1)) -> Lot:
    return Lot(
        lot_id=lot_id,
        sku="YOG",
        warehouse="W1",
        quantity=quantity,
        received_on=date(2026, 1, 1),
        expires_on=expires,
    )


def a_reservation(quantity: int, lot_id: str = "L1", reservation_id: str = "R1") -> Reservation:
    return Reservation(
        reservation_id=reservation_id,
        holder="shop",
        sku="YOG",
        warehouse="W1",
        lots=((lot_id, quantity),),
    )


def test_receiving_makes_stock_available():
    assert a_stock(a_lot()).available("YOG", "W1", now=DAY) == 100


def test_a_reservation_takes_stock_out_of_availability():
    stock = a_stock(a_lot())
    stock.reserve(a_reservation(40), on=DAY)
    assert stock.available("YOG", "W1", now=DAY) == 60


def test_a_reservation_asks_for_more_than_there_is_and_holds_nothing():
    stock = a_stock(a_lot(30))
    with pytest.raises(InsufficientStock):
        stock.reserve(a_reservation(40), on=DAY)
    assert stock.available("YOG", "W1", now=DAY) == 30


def test_committing_leaves_the_shelf():
    stock = a_stock(a_lot())
    stock.reserve(a_reservation(40), on=DAY)
    stock.commit("R1", 40, on=DAY)
    assert stock.on_hand("YOG", "W1") == 60
    assert stock.reservation("R1").held() == 0


def test_a_commit_of_more_than_the_reservation_holds_is_refused():
    stock = a_stock(a_lot())
    stock.reserve(a_reservation(40), on=DAY)
    with pytest.raises(NotEnoughReserved):
        stock.commit("R1", 41, on=DAY)


def test_a_release_gives_the_stock_back():
    stock = a_stock(a_lot())
    stock.reserve(a_reservation(40), on=DAY)
    stock.release("R1", on=DAY)
    assert stock.available("YOG", "W1", now=DAY) == 100
    assert stock.reservation("R1").held() == 0


def test_a_reservation_is_only_the_holder_s_to_move():
    stock = a_stock(a_lot())
    stock.reserve(a_reservation(10), on=DAY)
    with pytest.raises(ReservationNotHeld):
        stock.commit("R1", 5, holder="someone-else", on=DAY)


def test_an_expired_lot_is_not_available_but_is_still_on_hand():
    stock = a_stock(a_lot(quantity=100, expires=date(2026, 4, 1)))
    assert stock.available("YOG", "W1", now=DAY) == 0
    assert stock.on_hand("YOG", "W1") == 100


def test_a_write_off_removes_the_free_quantity_of_an_expired_lot():
    stock = a_stock(a_lot(quantity=100, expires=date(2026, 4, 1)))
    assert stock.write_off_expired(now=DAY) == ["L1"]
    assert stock.on_hand("YOG", "W1") == 0


def test_a_live_lot_is_left_alone_by_a_write_off():
    stock = a_stock(a_lot())
    assert stock.write_off_expired(now=DAY) == []
    assert stock.on_hand("YOG", "W1") == 100


def test_a_transfer_carries_the_stock_and_the_expiry_with_it():
    stock = a_stock(a_lot(quantity=100, expires=date(2026, 6, 1)))
    moved = stock.transfer("L1", 30, to_warehouse="W2", new_lot_id="L2", on=DAY)
    assert moved.expires_on == date(2026, 6, 1)
    assert stock.on_hand("YOG", "W2") == 30
    assert stock.on_hand("YOG", "W1") == 70


def test_a_transfer_out_of_an_expired_lot_is_refused():
    stock = a_stock(a_lot(quantity=100, expires=date(2026, 4, 1)))
    with pytest.raises(ExpiredLot):
        stock.transfer("L1", 10, to_warehouse="W2", new_lot_id="L2", on=DAY)


def test_every_movement_is_written_to_the_ledger():
    stock = a_stock(a_lot())
    stock.reserve(a_reservation(10), on=DAY)
    stock.commit("R1", 10, on=DAY)
    assert [movement.caused_by for movement in stock.movements()] == [
        "receive",
        "reserve",
        "commit",
    ]
