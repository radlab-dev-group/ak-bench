"""Leases: one holder at a time, and a dead holder stays dead.

A lease is held for ``ttl`` seconds from the moment it is taken. Time is
injected, so a test can move the clock instead of sleeping; the clock is a
callable returning seconds, and it never goes backwards.

The rules
    * ``acquire`` succeeds when the resource is free or its hold has expired.
      Every successful acquisition raises the resource's **epoch** by one, and
      the epoch is what tells two holders of the same resource apart.
    * ``renew`` extends a lease that is still live. It is refused when the
      caller is not the current holder (``LeaseHeld``) and when the deadline
      has passed (``LeaseExpired``): a process that stopped talking cannot
      resume a lease it let die, because another holder may already be working.
    * ``release`` is a no-op for a lease that is not the current one. Dropping
      a lease you no longer hold must not free somebody else's resource.
    * ``is_valid`` is the only question that matters while work is in flight:
      it is true exactly while the lease is the current one and its deadline
      has not passed.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from cadence.errors import LeaseExpired, LeaseHeld


@dataclass(frozen=True)
class Lease:
    """What a holder was given: the resource, its epoch, and a deadline."""

    resource: str
    holder: str
    epoch: int
    taken_at: float
    until: float

    def held_by(self, holder: str, epoch: int) -> bool:
        return self.holder == holder and self.epoch == epoch

    def expired_at(self, now: float) -> bool:
        return now >= self.until


class LeaseBook:
    """The resource is granted to one holder at a time, with expiring leases."""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock if clock is not None else time.monotonic
        self._held: dict[str, Lease] = {}
        self._epochs: dict[str, int] = {}

    def now(self) -> float:
        return self._clock()

    def holder_of(self, resource: str) -> Lease | None:
        """The live lease, or ``None`` when nobody holds the resource."""
        lease = self._held.get(resource)
        if lease is None or lease.expired_at(self.now()):
            return None
        return lease

    def acquire(self, resource: str, holder: str, *, ttl: float) -> Lease:
        """Take the resource, or explain who holds it."""
        if ttl <= 0:
            raise ValueError(f"ttl must be positive, got {ttl}")
        current = self.holder_of(resource)
        if current is not None:
            raise LeaseHeld(resource, current.holder, current.until)
        epoch = self._epochs.get(resource, 0) + 1
        self._epochs[resource] = epoch
        lease = Lease(
            resource=resource,
            holder=holder,
            epoch=epoch,
            taken_at=self.now(),
            until=self.now() + ttl,
        )
        self._held[resource] = lease
        return lease

    def takeover(self, resource: str, holder: str, *, epoch: int, ttl: float) -> Lease:
        """Take a resource back from its current holder, if this caller is that holder.

        A worker that was cut off and comes back still believes it holds the
        resource, and asks for it back by the epoch it was given. The epoch is
        the whole question: a request for an epoch the book no longer carries is
        stale — somebody else was granted the resource while the caller was
        silent — and granting it would put two workers on the same work. So a
        stale epoch is refused with :class:`~cadence.errors.LeaseHeld`, and the
        current holder keeps its lease and its validity.
        """
        if ttl <= 0:
            raise ValueError(f"ttl must be positive, got {ttl}")
        current = self.holder_of(resource)
        if current is None:
            return self.acquire(resource, holder, ttl=ttl)
        if current.epoch != epoch:
            raise LeaseHeld(resource, current.holder, current.until)
        taken = replace(current, holder=holder, taken_at=self.now(), until=self.now() + ttl)
        self._held[resource] = taken
        return taken

    def renew(self, lease: Lease, *, ttl: float) -> Lease:
        """Extend a lease that is still live; never revive a dead one.

        A lease whose deadline has passed is dropped here rather than kept, so
        that the holder that let it die cannot come back and the next
        ``acquire`` sees a free resource.
        """
        if ttl <= 0:
            raise ValueError(f"ttl must be positive, got {ttl}")
        current = self._held.get(lease.resource)
        if current is None or not current.held_by(lease.holder, lease.epoch):
            raise LeaseHeld(lease.resource, current.holder if current else "-", 0.0)
        if current.expired_at(self.now()):
            del self._held[lease.resource]
            raise LeaseExpired(lease.resource, lease.holder, lease.epoch)
        extended = replace(current, until=self.now() + ttl)
        self._held[lease.resource] = extended
        return extended

    def release(self, lease: Lease) -> bool:
        """Give the resource back. Only the current holder can do it."""
        current = self._held.get(lease.resource)
        if current is None or not current.held_by(lease.holder, lease.epoch):
            return False
        del self._held[lease.resource]
        return True

    def is_valid(self, lease: Lease) -> bool:
        """Whether the lease still authorises its holder right now."""
        current = self._held.get(lease.resource)
        return bool(
            current is not None
            and current.held_by(lease.holder, lease.epoch)
            and not current.expired_at(self.now())
        )

    def resources(self) -> list[str]:
        return sorted(self._held)
