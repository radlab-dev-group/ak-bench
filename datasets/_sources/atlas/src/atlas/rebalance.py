"""Rebalancing: build a plan, move the keys, publish the plan.

The sequence is fixed and every step is observable:

1. **build** a plan for the new membership, at the epoch the change will
   commit at;
2. **compute** the movement: keys whose primary differs between the current
   plan and the new one, taken from the state actually stored, not from a
   sample;
3. **stream** each moved range to its new primary and catch the destination
   up, while the *current* plan still routes writes to the old primary;
4. **publish** the new plan, which is the switch: from that moment writes for
   the moved keys route to their new primary;
5. **release** the source replicas, and only then.

Publishing before the stream (step 4 before 3) sends writes to a replica that
does not hold the key; releasing before the stream loses the key. Neither is
visible in a single write, and both are visible in the store after a
rebalance that went through this code path, which is why the order is written
down here rather than discovered.

Writes that were admitted under the previous plan and land after publication
are not an error to be handled here: a write carries the plan epoch it was
planned under, and the fencing check is what refuses it if the epoch is gone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .migration import Checkpoint, Migrator
from .placement import Plan, PlacementService


@dataclass
class Movement:
    key: str
    shard: int
    source: str
    destination: str


@dataclass
class RebalanceReport:
    epoch: int
    moved: list[Movement] = field(default_factory=list)
    copied: int = 0
    checkpoints: list[Checkpoint] = field(default_factory=list)
    published: bool = False
    released: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def moved_keys(self) -> list[str]:
        return sorted({movement.key for movement in self.moved})


class Rebalancer:
    def __init__(
        self,
        nodes,
        *,
        placement: PlacementService,
        config,
        migrator: Migrator | None = None,
        shard_of,
    ) -> None:
        self.nodes = nodes
        self.placement = placement
        self.config = config
        self.migrator = migrator or Migrator(nodes, config=config)
        self._shard_of = shard_of

    def plan_for(self, replicas, *, epoch: int) -> Plan:
        return Plan.build(epoch, replicas, vnodes=int(self.config["vnodes"]))

    def movements(self, target: Plan, state_keys) -> list[Movement]:
        """Keys that change primary between the current plan and ``target``."""

        current = self.placement.current
        found: list[Movement] = []
        for key in sorted(state_keys):
            source = current.owner(key)
            destination = target.owner(key)
            if source == destination:
                continue
            found.append(
                Movement(
                    key=key,
                    shard=self._shard_of(key),
                    source=source,
                    destination=destination,
                )
            )
        return found

    def run(self, replicas, *, state_keys, epoch: int | None = None) -> RebalanceReport:
        """Execute the five steps. The report is the audit trail."""

        next_epoch = epoch if epoch is not None else self.placement.epoch() + 1
        target = self.plan_for(replicas, epoch=next_epoch)
        movements = self.movements(target, state_keys)
        report = RebalanceReport(epoch=next_epoch, moved=movements)

        by_pair: dict[tuple[int, str, str], list[str]] = {}
        for movement in movements:
            by_pair.setdefault((movement.shard, movement.source, movement.destination), []).append(
                movement.key
            )
        for (shard, source, destination), keys in sorted(by_pair.items()):
            if source not in self.nodes or destination not in self.nodes:
                report.notes.append(f"skipped shard {shard}: {source} -> {destination} is not in the cluster")
                continue
            checkpoint = self.migrator.copy_range(
                shard, source=source, destination=destination, keys=set(keys)
            )
            report.copied += checkpoint.copied
            report.checkpoints.append(checkpoint)

        self.placement.publish(target)
        report.published = True

        for (shard, source, _destination), keys in sorted(by_pair.items()):
            if source not in self.nodes:
                continue
            checkpoint = next(
                (item for item in report.checkpoints if item.shard == shard and item.source == source),
                None,
            )
            if checkpoint is None:
                continue
            report.checkpoints = [
                item for item in report.checkpoints if not (item.shard == shard and item.source == source)
            ]
            report.checkpoints.append(self.migrator.release(checkpoint, keys=set(keys)))
            self.migrator.finish(report.checkpoints[-1])
            report.released.append(f"{source}:{shard}")
        return report
