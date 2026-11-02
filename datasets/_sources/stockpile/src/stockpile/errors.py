"""The whole exception hierarchy of the stock engine.

Every failure the engine can produce is a :class:`StockError`, so a caller can
catch one name. The subclasses name what was refused, because "there is not
enough" is only useful when it says what, how much, and where.
"""

from __future__ import annotations


class StockError(Exception):
    """Base class for everything stockpile refuses."""


class UnknownLot(StockError):
    """A lot id the stock does not hold."""

    def __init__(self, lot_id: str) -> None:
        super().__init__(f"unknown lot: {lot_id}")
        self.lot_id = lot_id


class DuplicateLot(StockError):
    """The stock already holds a lot with this id."""

    def __init__(self, lot_id: str) -> None:
        super().__init__(f"lot already received: {lot_id}")
        self.lot_id = lot_id


class UnknownSku(StockError):
    """A sku the catalogue does not hold."""

    def __init__(self, sku: str) -> None:
        super().__init__(f"unknown sku: {sku}")
        self.sku = sku


class InsufficientStock(StockError):
    """The request asks for more than the stock can give."""

    def __init__(self, sku: str, requested: int, available: int) -> None:
        super().__init__(
            f"not enough {sku}: requested {requested}, available {available}"
        )
        self.sku = sku
        self.requested = requested
        self.available = available


class ReservationNotHeld(StockError):
    """The caller is not the holder of this reservation."""

    def __init__(self, reservation_id: str) -> None:
        super().__init__(f"reservation not held by caller: {reservation_id}")
        self.reservation_id = reservation_id


class NotEnoughReserved(StockError):
    """Committing asks for more than the reservation holds."""

    def __init__(self, reservation_id: str, requested: int, held: int) -> None:
        super().__init__(
            f"reservation {reservation_id} holds {held}, cannot commit {requested}"
        )
        self.reservation_id = reservation_id
        self.requested = requested
        self.held = held


class ExpiredLot(StockError):
    """A lot that has passed its expiry cannot move again."""

    def __init__(self, lot_id: str, expired_on: object) -> None:
        super().__init__(f"lot expired on {expired_on}: {lot_id}")
        self.lot_id = lot_id
        self.expired_on = expired_on


class TransferImpossible(StockError):
    """A transfer the stock cannot make: too little there, or the lot is gone."""

    def __init__(self, lot_id: str, reason: str) -> None:
        super().__init__(f"cannot transfer {lot_id}: {reason}")
        self.lot_id = lot_id
        self.reason = reason
