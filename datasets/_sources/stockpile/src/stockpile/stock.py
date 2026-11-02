"""The stock: what is where, who has claimed it, and how a claim moves.

Reserving is not taking. A reservation says that a quantity of a lot is held for
somebody, so that the warehouse does not sell it twice; committing is the moment
it is actually gone from the shelf. The difference is the whole reason a stock
engine exists, and it is where the accounting has to be exact.

The lifecycle of a claim
    ``reserve`` takes free quantity out of the lots and records a reservation.
    ``commit`` turns part or all of a reservation into stock that has left the
    shelf: the quantity leaves the lot, and the reservation gives up what it
    held. ``release`` gives reserved quantity back to the lots so it can be
    claimed by somebody else.

    A reservation that has been fully committed or released holds nothing, and
    asking for more than it holds is refused. Nothing is ever lost: for one
    reservation, the sum of what it still holds, what it has committed and what
    it has released is constant across the three operations.

Availability
    ``available`` is the free quantity of the lots that are still useable, which
    means a lot that has expired does not count, and neither does the part of a
    live lot that is already reserved or committed. ``on_hand`` is the opposite
    extreme: everything the warehouse physically holds, expired or claimed,
    because the shelf does not care what the ledger says.

    The two numbers answer different questions and are never interchangeable.

Movements
    Every movement of stock is recorded, in order, with what caused it. The
    ledger is what makes a discrepancy traceable to one event.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from stockpile.errors import (
    DuplicateLot,
    ExpiredLot,
    InsufficientStock,
    NotEnoughReserved,
    ReservationNotHeld,
    TransferImpossible,
    UnknownLot,
)
from stockpile.lots import Lot


@dataclass(frozen=True)
class Reservation:
    """A claim on quantity, held by a holder, across one or more lots."""

    reservation_id: str
    holder: str
    sku: str
    warehouse: str
    lots: tuple[tuple[str, int], ...]
    committed: int = 0
    released: int = 0

    def held(self) -> int:
        """What this reservation still holds, across the lots it was written against."""
        return sum(quantity for _lot_id, quantity in self.lots)

    def claimed(self) -> int:
        """Everything this reservation was ever written for: held, committed and released."""
        return self.held() + self.committed + self.released

    def of_lot(self, lot_id: str) -> int:
        return sum(quantity for id_, quantity in self.lots if id_ == lot_id)


@dataclass(frozen=True)
class Movement:
    """One line of the movement ledger."""

    caused_by: str
    sku: str
    warehouse: str
    quantity: int
    on: date


class Stock:
    """Everything the warehouse has, and the only ways a claim may move."""

    def __init__(self) -> None:
        self._lots: dict[str, Lot] = {}
        self._reservations: dict[str, Reservation] = {}
        self._movements: list[Movement] = []

    # -- receiving ---------------------------------------------------------

    def receive(self, lot: Lot) -> Lot:
        """Put a lot on the shelf, refusing a lot id already received."""
        if lot.lot_id in self._lots:
            raise DuplicateLot(lot.lot_id)
        self._lots[lot.lot_id] = lot
        self._log("receive", lot.sku, lot.warehouse, lot.quantity, lot.received_on)
        return lot

    # -- availability ------------------------------------------------------

    def lot(self, lot_id: str) -> Lot:
        try:
            return self._lots[lot_id]
        except KeyError:
            raise UnknownLot(lot_id) from None

    def lots_of(self, sku: str, warehouse: str | None = None) -> list[Lot]:
        """The lots of one sku, optionally in one warehouse, oldest receipt first."""
        found = [lot for lot in self._lots.values() if lot.sku == sku]
        if warehouse is not None:
            found = [lot for lot in found if lot.warehouse == warehouse]
        return sorted(found, key=lambda lot: (lot.received_on, lot.lot_id))

    def available(self, sku: str, warehouse: str | None = None, *, now: date) -> int:
        """Free quantity of the useable lots; an expired lot is not available."""
        return sum(
            lot.free() for lot in self.lots_of(sku, warehouse) if not lot.is_expired(now)
        )

    def on_hand(self, sku: str, warehouse: str | None = None) -> int:
        """Everything physically there, expired or claimed."""
        return sum(lot.quantity for lot in self.lots_of(sku, warehouse))

    # -- reservations ------------------------------------------------------

    def reserve(self, reservation: Reservation, *, on: date) -> Reservation:
        """Hold a reservation's lots against the stock, or refuse and hold nothing."""
        for lot_id, quantity in reservation.lots:
            lot = self.lot(lot_id)
            if lot.free() < quantity:
                raise InsufficientStock(lot.sku, quantity, lot.free())
        for lot_id, quantity in reservation.lots:
            self.lot(lot_id).reserved += quantity
        self._reservations[reservation.reservation_id] = reservation
        self._log(
            "reserve", reservation.sku, reservation.warehouse, reservation.held(), on
        )
        return reservation

    def reservation(self, reservation_id: str) -> Reservation:
        try:
            return self._reservations[reservation_id]
        except KeyError:
            raise ReservationNotHeld(reservation_id) from None

    def commit(
        self,
        reservation_id: str,
        quantity: int,
        *,
        holder: str | None = None,
        on: date,
    ) -> Reservation:
        """Move committed quantity off the shelf; the reservation gives it up."""
        reservation = self.reservation(reservation_id)
        if holder is not None and reservation.holder != holder:
            raise ReservationNotHeld(reservation_id)
        held = reservation.held()
        if quantity > held:
            raise NotEnoughReserved(reservation_id, quantity, held)

        remaining = quantity
        lots = list(reservation.lots)
        for index, (lot_id, still) in enumerate(lots):
            if remaining <= 0:
                continue
            take = min(still, remaining)
            lot = self.lot(lot_id)
            lot.reserved -= take
            lot.quantity -= take
            lots[index] = (lot_id, still - take)
            remaining -= take
        self._reservations[reservation_id] = Reservation(
            reservation_id=reservation.reservation_id,
            holder=reservation.holder,
            sku=reservation.sku,
            warehouse=reservation.warehouse,
            lots=tuple(lots),
            committed=reservation.committed + quantity,
            released=reservation.released,
        )
        self._log("commit", reservation.sku, reservation.warehouse, quantity, on)
        return self._reservations[reservation_id]

    def release(
        self,
        reservation_id: str,
        quantity: int | None = None,
        *,
        holder: str | None = None,
        on: date,
    ) -> Reservation:
        """Give reserved quantity back to the lots so it can be claimed again.

        ``quantity`` of ``None`` releases everything the reservation still
        holds. A partial release gives back exactly ``quantity`` and leaves the
        reservation holding the rest.
        """
        reservation = self.reservation(reservation_id)
        if holder is not None and reservation.holder != holder:
            raise ReservationNotHeld(reservation_id)
        held = reservation.held()
        amount = held if quantity is None else quantity
        if amount > held:
            raise NotEnoughReserved(reservation_id, amount, held)

        remaining = amount
        lots = list(reservation.lots)
        for index, (lot_id, still) in enumerate(lots):
            if remaining <= 0:
                continue
            take = min(still, remaining)
            self.lot(lot_id).reserved -= take
            lots[index] = (lot_id, still - take)
            remaining -= take
        self._reservations[reservation_id] = Reservation(
            reservation_id=reservation.reservation_id,
            holder=reservation.holder,
            sku=reservation.sku,
            warehouse=reservation.warehouse,
            lots=tuple(lots),
            committed=reservation.committed,
            released=reservation.released + amount,
        )
        self._log("release", reservation.sku, reservation.warehouse, amount, on)
        return self._reservations[reservation_id]

    # -- movements between warehouses --------------------------------------

    def transfer(
        self,
        lot_id: str,
        quantity: int,
        *,
        to_warehouse: str,
        new_lot_id: str,
        on: date,
    ) -> Lot:
        """Move free quantity of a lot to another warehouse as a new lot."""
        lot = self.lot(lot_id)
        if lot.is_expired(on):
            raise ExpiredLot(lot_id, lot.expires_on)
        if lot.free() < quantity:
            raise TransferImpossible(lot_id, f"only {lot.free()} free")
        if new_lot_id in self._lots:
            raise TransferImpossible(lot_id, f"lot {new_lot_id} already exists")
        lot.quantity -= quantity
        moved = Lot(
            lot_id=new_lot_id,
            sku=lot.sku,
            warehouse=to_warehouse,
            quantity=quantity,
            received_on=lot.received_on,
            expires_on=lot.expires_on,
        )
        self._lots[new_lot_id] = moved
        self._log("transfer", lot.sku, to_warehouse, quantity, on)
        return moved

    def write_off_expired(self, *, now: date) -> list[str]:
        """Remove the free quantity of every expired lot; return the lots written off.

        Committed quantity is already off the shelf, and reserved quantity is
        somebody's claim, so neither is written off: a write-off removes only
        what is free, and the lot stays alive while a claim still rides on it.
        """
        written: list[str] = []
        for lot in sorted(self._lots.values(), key=lambda item: item.lot_id):
            if not lot.is_expired(now) or lot.free() <= 0:
                continue
            amount = lot.free()
            lot.quantity = lot.reserved
            self._log("write-off", lot.sku, lot.warehouse, amount, now)
            written.append(lot.lot_id)
        return written

    # -- ledger ------------------------------------------------------------

    def movements(self) -> list[Movement]:
        return list(self._movements)

    def _log(self, caused_by: str, sku: str, warehouse: str, quantity: int, on: date) -> None:
        self._movements.append(Movement(caused_by, sku, warehouse, quantity, on))

    def __len__(self) -> int:
        return len(self._lots)
