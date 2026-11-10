# Atlas

Atlas is a sharded, replicated, fenced key-value store. It is a benchmark
seed: standard library only, no network, no threads, no wall-clock races, and
no behaviour that a test cannot reproduce by calling methods in a fixed order.

`SPEC.md` is the normative contract. This README is the map. Where the two
disagree, `SPEC.md` is right.

```
PYTHONPATH=src python -m pytest tests          # the repository suite
PYTHONPATH=src python -m atlas.cli --help      # the operator driver
PYTHONPATH=src python tools/parity.py          # differential harness
```

## What is here

| Module | Owns |
| --- | --- |
| `atlas.store` | the public `Atlas` API; the write path and its order of checks |
| `atlas.config` | five configuration layers and their precedence |
| `atlas.ring` | consistent hashing; the placement answer for one key |
| `atlas.placement` | plans: ring plus epoch, published immutably |
| `atlas.membership` | epochs; who is in the cluster |
| `atlas.fencing` | the generation check and the epoch check at commit time |
| `atlas.replication` | quorum writes and reads across replica nodes |
| `atlas.repair` | read repair; which version of a key wins |
| `atlas.antientropy` | digest walks; divergence no read would have found |
| `atlas.migration` | copying a shard range, with a resumable checkpoint |
| `atlas.rebalance` | the five steps that move keys and publish a plan |
| `atlas.storage` | one shard: memtable, log, snapshot, recovery |
| `atlas.wal` | frames, transactions, and torn-tail repair |
| `atlas.snapshot` | snapshot files and the CURRENT publication pointer |
| `atlas.clock` | the log sequence and the snapshot boundary convention |
| `atlas.vclock` | version vectors and the concurrency tie-break |
| `atlas.registry` | the strategy tables the configuration resolves against |
| `atlas.schema` / `atlas.tables` | the row shape; the tables are generated |
| `atlas.transaction` | optimistic transactions that fence on the read set |
| `atlas.retention` | tombstone ageing |
| `atlas.audit` | the authority trail, including refusals |
| `atlas.cache` | a read cache that misses rather than lie |
| `atlas.faults` | deterministic crash injection points |
| `atlas.compat`, `atlas.vendor.ring` | deprecated v1 shims, not the write path |
| `atlas.lineage` | provenance: **declared, not implemented** |
| `atlas.evolution` | schema evolution of stored rows: **declared, not implemented**; guide in `docs/schema-evolution.md` |

## The five rules everything else follows from

1. **A transaction is durable when its `COMMIT` frame is durable.** Repairing
   a torn tail never discards a committed transaction and never keeps a
   partial one.
2. **CURRENT is the publication decision.** A snapshot file that CURRENT does
   not name does not exist as far as recovery is concerned.
3. **A snapshot at LSN `N` already contains record `N`.** Recovery applies
   records strictly after `N`; the convention is configured, not improvised.
4. **Fencing is an equality.** An offered generation that is not the current
   one is refused in either direction under a strict check, and an epoch that
   is gone is refused always.
5. **Concurrent writes are settled by the greatest writer identifier.** Every
   replica must reach the same winner or repair makes the divergence permanent.

## Where the sharp edges are

`atlas/compat.py` and `atlas/vendor/ring.py` are v1 shims. They compute
placement differently on purpose, because that is what v1 clients compute.
Neither is on the write path: `atlas.store.shard_of` is the shard answer and
`atlas.placement.PlacementService.owner` is the owner answer, and both are
derived from `atlas.ring`, never from the vendored ring.

`src/atlas/tables.py` is generated from `schema/tables.json` by hand-running
`python -m atlas.tables --write` after an edit to the document. Editing the
module itself is not a change; the next regeneration takes the edit back.

`tools/parity.py` compares the store against a deliberately naive model. It
is the fastest way to see a divergence and the slowest way to understand one:
the model knows three rules, and the store has more than three.

## Status

The store is complete and its suite passes. Two features are declared and not
implemented: `atlas.lineage` (`SPEC.md` section 9) and `atlas.evolution`
(`SPEC.md` section 10).
