"""Lots: the unit of stock, and the questions availability answers about it.

A lot is how much of one sku arrived at one warehouse, on one day, and until
what day it may still be used. Availability is never a property of the sku
alone — it is a property of the lots that hold it — because a warehouse with
two lots of the same sku, one expiring tomorrow and one next year, does not
have the same stock as a warehouse with two lots that both expire next year.

The rules
    * ``free`` is what a new reservation could still take: the lot's quantity
      minus what a reservation is holding. It never goes below zero, because a
      lot cannot give away more than it holds.
    * ``is_expired`` compares the lot's expiry date to a *now* date: a lot that
      expires **on** the day is still usable that day and expired the day after.
      The expiry is inclusive of its own day, which is what makes an FEFO run
      on the last day still see the lot.
    * ``useable`` is the question that matters for every movement: the lot is
      not expired and still has free quantity. An expired lot with quantity in
      it is still counted for the books — it has to be written off — but it is
      not useable for a new reservation or a transfer out.

Committed quantity is not a field of a lot: once a claim is committed it has
left the shelf, so the lot simply holds less, and the reservation keeps the
audit trail of what it committed and what it released.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class Lot:
    """A quantity of one sku, in one warehouse, usable until a date."""

    lot_id: str
    sku: str
    warehouse: str
    quantity: int
    received_on: date
    expires_on: date
    reserved: int = 0

    def __post_init__(self) -> None:
        if self.quantity < 0:
            raise ValueError(f"quantity cannot be negative, got {self.quantity}")
        if self.reserved < 0:
            raise ValueError(f"reserved cannot be negative, got {self.reserved}")
        if self.reserved > self.quantity:
            raise ValueError(f"lot {self.lot_id}: reserved exceeds quantity")

    def free(self) -> int:
        """What a new reservation could still take from this lot."""
        return self.quantity - self.reserved

    def is_expired(self, now: date) -> bool:
        return now > self.expires_on

    def useable(self, now: date) -> bool:
        return not self.is_expired(now) and self.free() > 0
