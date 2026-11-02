"""stockpile: lots, expiry, reservations and transfers for one warehouse network.

The package is a benchmark fixture and is deliberately complete — a lot that
knows when it dies, a stock that refuses to oversell, and an allocation module
whose body is the task — because the tasks built on it are about one rule
behaving wrongly, not about a missing system.
"""

from stockpile.allocate import Allocation, Pick, allocate
from stockpile.errors import (
    DuplicateLot,
    InsufficientStock,
    NotEnoughReserved,
    StockError,
    UnknownLot,
)
from stockpile.lots import Lot
from stockpile.stock import Movement, Reservation, Stock

__all__ = [
    "Allocation",
    "DuplicateLot",
    "InsufficientStock",
    "Lot",
    "Movement",
    "NotEnoughReserved",
    "Pick",
    "Reservation",
    "Stock",
    "StockError",
    "UnknownLot",
    "allocate",
]
