"""Leases and the fencing checks of the write path.

A lease is granted per key and names the generation that holds it. Two checks
run at commit time, and they check different things:

* the **generation check** compares the generation the caller *offered* with
  the generation the store currently holds. This is equality. A greater
  offered generation means the caller has seen a write this replica has not,
  which is a protocol violation of the same class as a smaller one, and the
  configuration key ``generation_check`` selects whether a mismatch aborts
  the write (``strict``) or lets it through (``permissive``, for the v2
  migration where a peer is still catching up);
* the **epoch check** compares the epoch the write was planned under with the
  epoch the cluster has now. This is also equality, and it has no
  permissive mode, because a stale-epoch write is not a race the caller can
  retry, it is a node that was cut off and is now committing against a
  cluster that has moved on.

The order of the two checks is part of the contract: the epoch check runs
first, because a write from an epoch that is gone is wrong no matter which
generation it names.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import EpochMismatchError, StaleGenerationError
from .membership import Membership


@dataclass(frozen=True)
class Lease:
    key: str
    holder: str
    generation: int
    epoch: int


class FenceBook:
    """Tracks the leases a shard holds and the checks a write must pass."""

    def __init__(self, membership: Membership, *, generation_check: str = "strict") -> None:
        if generation_check not in ("strict", "permissive"):
            raise ValueError(f"generation_check must be strict or permissive, got {generation_check!r}")
        self.membership = membership
        self.generation_check = generation_check
        self.leases: dict[str, Lease] = {}

    def grant(self, key: str, holder: str, generation: int) -> Lease:
        lease = Lease(key=key, holder=holder, generation=generation, epoch=self.membership.epoch)
        self.leases[key] = lease
        return lease

    def lease(self, key: str) -> Lease | None:
        return self.leases.get(key)

    def release(self, key: str) -> Lease | None:
        return self.leases.pop(key, None)

    def check_write(
        self,
        key: str,
        *,
        writer: str,
        offered_generation: int,
        planned_epoch: int,
    ) -> None:
        """Run both checks, epoch first, and raise on either violation.

        ``offered_generation`` is the generation the writer read. The store's
        current generation for the key is compared to it: with a strict check
        a mismatch in either direction is an error; with a permissive check a
        *smaller* offered generation is allowed, which is the case of a peer
        that is catching up, while a *greater* one is still refused, because
        a peer ahead of the primary means the primary has been bypassed.
        """

        self.membership.check_epoch(writer, planned_epoch)
        current = self.leases.get(key)
        held = current.generation if current is not None else 0
        if self.generation_check == "strict":
            if offered_generation != held:
                raise StaleGenerationError(key, offered_generation, held)
        else:
            if offered_generation > held:
                raise StaleGenerationError(key, offered_generation, held)

    def acknowledge(self, key: str, offered_generation: int, planned_epoch: int, writer: str) -> None:
        """A commit acknowledgment is a write that only carries the check."""

        self.check_write(key, writer=writer, offered_generation=offered_generation, planned_epoch=planned_epoch)

    def current_generation(self, key: str) -> int:
        lease = self.leases.get(key)
        return lease.generation if lease is not None else 0

    def advance_lease(self, key: str, holder: str, generation: int) -> Lease:
        """Move the key's lease to ``holder`` at ``generation``.

        A new holder takes over only forward in generation: a holder offering
        a generation at or below the one on record has not seen the write that
        the recorded holder made, and taking over from that position is the
        stale-worker failure the lease exists to stop. The holder is recorded
        for audit; the check that matters is the generation.
        """

        previous = self.leases.get(key)
        if previous is not None and generation <= previous.generation:
            raise StaleGenerationError(key, previous.generation, generation)
        return self.grant(key, holder, generation)
