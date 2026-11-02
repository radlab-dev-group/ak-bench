"""First expired, first out. The rules are this docstring; writing them is the task.

``allocate(stock, sku, quantity, *, warehouse, now, already_planned=None)``
decides which lots a request should be filled from and returns an
:class:`Allocation`. It is a **plan**, not a movement: nothing is reserved, the
stock is read and never modified, and calling it twice with the same arguments
returns the same plan.

What may be allocated from
    A lot is eligible when it holds the sku, sits in ``warehouse``, is not
    expired at ``now`` — a lot that expires **on** ``now`` is still eligible,
    because it is only gone the day after — and still has free quantity.

    A lot's free quantity is reduced by whatever ``already_planned`` says is
    promised to a plan that has been written but not yet reserved:
    ``stock.lot(lot_id).free() - already_planned.get(lot_id, 0)``. A lot whose
    remaining quantity this way drops to zero is not eligible, and a plan must
    never allocate more from a lot than that remaining quantity.

In which order
    Earliest ``expires_on`` first — that is what FEFO means, the stock that has
    to go first goes first. Two lots that expire on the same day are taken
    oldest-receipt first, and a remaining tie breaks on the lot id. The order of
    ``picks`` is that order, and it never changes.

How much is taken
    The earliest eligible lot is drained as far as it can go, then the next,
    until the request is satisfied. A pick is never zero: a lot that
    contributes nothing does not appear. If the eligible lots cannot cover
    ``quantity`` the whole request is refused with
    :class:`~stockpile.errors.InsufficientStock`, carrying the sku, the
    requested quantity and the total that *was* allocatable — a partial plan is
    never returned, because an order that ships half its lines late is worse
    than one that is refused up front.

The result
    :class:`Allocation` holds ``picks`` (in the order above), the ``sku``, the
    ``warehouse`` and ``now`` it was planned for. ``picks`` always add up to
    ``quantity``, and :meth:`Allocation.to_reservation` turns the plan into a
    :class:`~stockpile.stock.Reservation` the caller can hand to
    :meth:`~stockpile.stock.Stock.reserve`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from stockpile.stock import Reservation, Stock


@dataclass(frozen=True)
class Pick:
    """One lot's share of an allocation."""

    lot_id: str
    quantity: int
    expires_on: date


@dataclass(frozen=True)
class Allocation:
    """The plan: which lots, how much from each, and what it is for."""

    sku: str
    warehouse: str
    now: date
    picks: tuple[Pick, ...] = ()

    @property
    def total(self) -> int:
        return sum(pick.quantity for pick in self.picks)

    def lots(self) -> list[str]:
        return [pick.lot_id for pick in self.picks]

    def to_reservation(self, reservation_id: str, holder: str) -> Reservation:
        """The plan as a reservation, ready for :meth:`Stock.reserve`."""
        return Reservation(
            reservation_id=reservation_id,
            holder=holder,
            sku=self.sku,
            warehouse=self.warehouse,
            lots=tuple((pick.lot_id, pick.quantity) for pick in self.picks),
        )


def allocate(
    stock: Stock,
    sku: str,
    quantity: int,
    *,
    warehouse: str,
    now: date,
    already_planned: Mapping[str, int] | None = None,
) -> Allocation:
    """Plan an FEFO allocation of ``quantity`` of ``sku`` from ``warehouse``."""
    raise NotImplementedError("allocate is specified in this module and not yet written")
