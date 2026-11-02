"""The FEFO contract, enforced on the plan the agent hands back.

Every rule in the module docstring has a test here: which lots may give, what
an earlier plan does to a lot, the order and its two tie-breaks, how much each
lot gives, the refusal of a request that cannot be covered, and the purity of
the whole thing. A wrong reading shows up as a wrong plan, not as an exception.
"""

from datetime import date

import pytest
from stockpile.allocate import allocate
from stockpile.errors import InsufficientStock
from stockpile.lots import Lot
from stockpile.stock import Reservation, Stock

NOW = date(2026, 5, 10)


def a_stock(*lots: Lot) -> Stock:
    stock = Stock()
    for lot in lots:
        stock.receive(lot)
    return stock


def a_lot(
    lot_id: str,
    quantity: int,
    expires: date,
    *,
    received: date = date(2026, 1, 1),
    warehouse: str = "W1",
    sku: str = "YOG",
) -> Lot:
    return Lot(
        lot_id=lot_id,
        sku=sku,
        warehouse=warehouse,
        quantity=quantity,
        received_on=received,
        expires_on=expires,
    )


def plan_for(stock: Stock, quantity: int, **kwargs) -> list[tuple[str, int]]:
    plan = allocate(stock, "YOG", quantity, warehouse="W1", now=NOW, **kwargs)
    return [(pick.lot_id, pick.quantity) for pick in plan.picks]


# --------------------------------------------------------------- eligibility


def test_a_lot_that_expires_today_is_still_eligible():
    stock = a_stock(a_lot("L1", 50, NOW))
    assert plan_for(stock, 50) == [("L1", 50)]


def test_a_lot_that_expired_yesterday_is_not_eligible():
    stock = a_stock(
        a_lot("L-gone", 50, date(2026, 5, 9)),
        a_lot("L-live", 50, date(2026, 6, 1)),
    )
    assert plan_for(stock, 50) == [("L-live", 50)]


def test_a_lot_in_another_warehouse_is_not_eligible():
    stock = a_stock(
        a_lot("L-elsewhere", 50, date(2026, 5, 20), warehouse="W2"),
        a_lot("L-here", 50, date(2026, 6, 1)),
    )
    assert plan_for(stock, 50) == [("L-here", 50)]


def test_another_sku_in_the_same_warehouse_is_not_eligible():
    stock = a_stock(
        a_lot("L-cheese", 50, date(2026, 5, 20), sku="CHS"),
        a_lot("L-yog", 50, date(2026, 6, 1)),
    )
    assert plan_for(stock, 50) == [("L-yog", 50)]


def test_the_reserved_part_of_a_lot_is_not_eligible():
    stock = a_stock(a_lot("L1", 100, date(2026, 6, 1)))
    stock.reserve(
        Reservation(
            reservation_id="R1",
            holder="shop",
            sku="YOG",
            warehouse="W1",
            lots=(("L1", 60),),
        ),
        on=NOW,
    )
    assert plan_for(stock, 40) == [("L1", 40)]
    with pytest.raises(InsufficientStock):
        allocate(stock, "YOG", 41, warehouse="W1", now=NOW)


# ------------------------------------------------------------------- ordering


def test_the_earliest_expiry_goes_first_and_is_drained_first():
    stock = a_stock(
        a_lot("L-late", 100, date(2026, 8, 1)),
        a_lot("L-mid", 30, date(2026, 6, 1)),
        a_lot("L-soon", 20, date(2026, 5, 20)),
    )
    assert plan_for(stock, 45) == [("L-soon", 20), ("L-mid", 25)]


def test_two_lots_with_the_same_expiry_take_the_older_receipt_first():
    stock = a_stock(
        a_lot("L-newer", 50, date(2026, 6, 1), received=date(2026, 3, 1)),
        a_lot("L-older", 50, date(2026, 6, 1), received=date(2026, 2, 1)),
    )
    assert plan_for(stock, 60) == [("L-older", 50), ("L-newer", 10)]


def test_a_full_tie_breaks_on_the_lot_id():
    stock = a_stock(
        a_lot("L-b", 50, date(2026, 6, 1)),
        a_lot("L-a", 50, date(2026, 6, 1)),
    )
    assert plan_for(stock, 60) == [("L-a", 50), ("L-b", 10)]


# ------------------------------------------------------- already_planned


def test_a_lot_promise_from_an_earlier_plan_is_not_sold_twice():
    stock = a_stock(a_lot("L1", 100, date(2026, 6, 1)))
    assert plan_for(stock, 40, already_planned={"L1": 60}) == [("L1", 40)]


def test_a_lot_fully_promised_to_an_earlier_plan_is_skipped():
    stock = a_stock(
        a_lot("L-soon", 40, date(2026, 5, 20)),
        a_lot("L-late", 40, date(2026, 6, 1)),
    )
    assert plan_for(stock, 30, already_planned={"L-soon": 40}) == [("L-late", 30)]


def test_an_earlier_plan_never_makes_a_lot_give_more_than_it_has():
    stock = a_stock(a_lot("L1", 100, date(2026, 6, 1)))
    with pytest.raises(InsufficientStock):
        allocate(stock, "YOG", 50, warehouse="W1", now=NOW, already_planned={"L1": 60})


# ------------------------------------------------------------------- amounts


def test_a_request_that_exactly_empties_the_eligible_lots_is_planned():
    stock = a_stock(
        a_lot("L1", 30, date(2026, 5, 20)),
        a_lot("L2", 20, date(2026, 6, 1)),
    )
    assert plan_for(stock, 50) == [("L1", 30), ("L2", 20)]


def test_a_lot_that_gives_nothing_does_not_appear_in_the_plan():
    stock = a_stock(
        a_lot("L-soon", 10, date(2026, 5, 20)),
        a_lot("L-late", 10, date(2026, 6, 1)),
    )
    assert plan_for(stock, 10) == [("L-soon", 10)]


def test_a_refusal_reports_the_total_that_was_allocatable():
    stock = a_stock(
        a_lot("L1", 30, date(2026, 5, 20)),
        a_lot("L2", 20, date(2026, 6, 1)),
    )
    with pytest.raises(InsufficientStock) as refused:
        allocate(stock, "YOG", 60, warehouse="W1", now=NOW)
    assert refused.value.requested == 60
    assert refused.value.available == 50


# ------------------------------------------------------------------ the plan


def test_the_plan_turns_into_a_reservation_the_stock_can_hold():
    stock = a_stock(
        a_lot("L-soon", 10, date(2026, 5, 20)),
        a_lot("L-late", 10, date(2026, 6, 1)),
    )
    plan = allocate(stock, "YOG", 15, warehouse="W1", now=NOW)
    reservation = plan.to_reservation("R1", "shop")
    stock.reserve(reservation, on=NOW)
    assert stock.available("YOG", "W1", now=NOW) == 5
    assert reservation.of_lot("L-soon") == 10


def test_the_plan_is_pure_and_deterministic():
    stock = a_stock(
        a_lot("L-soon", 10, date(2026, 5, 20)),
        a_lot("L-late", 10, date(2026, 6, 1)),
    )
    first = allocate(stock, "YOG", 15, warehouse="W1", now=NOW)
    assert stock.on_hand("YOG", "W1") == 20
    assert stock.available("YOG", "W1", now=NOW) == 20
    second = allocate(stock, "YOG", 15, warehouse="W1", now=NOW)
    assert first == second
