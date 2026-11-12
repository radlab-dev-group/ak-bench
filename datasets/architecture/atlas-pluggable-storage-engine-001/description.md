# One shard's state has no boundary

`ShardStorage.__init__` builds everything a shard owns — the memtable, the
write-ahead log, the snapshot store — and the rest of the store calls its
methods. That is one object doing two jobs: it decides *what* a shard stores
and *where* it stores it. Two things follow, and both hurt today.

A test that wants a cluster of three replicas in memory still pays for a
filesystem, because opening a node opens directories, a WAL and a CURRENT file.
And a second storage format — anything that is not "memtable plus log plus
snapshot in a directory" — has no place to be written, because the code that
would use it constructs the one it does not want.

Draw the boundary. One protocol, two engines, injected from the top.

## What to build

A new package `src/atlas/engines/` holding the boundary and both engines:

- `atlas.engines.base.StorageEngine` — a `typing.Protocol`, `runtime_checkable`,
  describing one shard's record store:

  | method | meaning |
  | :--- | :--- |
  | `get(key)` | the record for `key`, or `None`; never mutates |
  | `put(record)` | store the record; `True` when the store changed, `False` when that exact record was already there |
  | `scan(low=None, high=None)` | records with `low <= key < high`, in ascending key order; both bounds optional |
  | `compact()` | drop what the store no longer needs; safe to call twice |
  | `flush()` | make what has been written durable, durable; safe to call twice |

  Which record may overwrite which is policy, and policy stays where it is
  today: in the store and its fencing checks. The engine is a dumb record
  store, which is exactly why a second one is possible.

  The two engines are constructed as `MemoryStorageEngine()` and
  `DiskStorageEngine(directory)` — one directory, one shard — and both are
  exported from `atlas.engines`.

- `atlas.engines.memory.MemoryStorageEngine` — the same semantics with no I/O
  at all, for tests and simulations.
- `atlas.engines.disk.DiskStorageEngine` — today's behaviour, moved: the WAL,
  the snapshot and the memtable it wraps stay the contract, including the
  recovery rules in `docs/adr/ADR-0014-storage-boundaries.md`.
- `atlas.engines.ShardStorage` reaches its engine through an attribute named
  `engine`, so a caller can see which engine a shard is on.

The store chooses the engine, not the shard: `Atlas(..., engine="disk")` is the
default and today's behaviour; `Atlas(..., engine="memory")` runs a whole
cluster in RAM. `engine` also accepts an engine instance or a callable, which
is how a test builds a cluster on a deliberately odd engine.

## What must not change

- `atlas.store.Atlas` is the API callers use. `put`, `get`, `resolve`, `delete`
  and `current_generation` keep their signatures, their results and their
  errors, and `python -m pytest tests/` stays green — that suite is the
  behaviour you are preserving, not something to update.
- The bytes on disk do not change. A cluster written by the base commit opens
  after your change.
- Imports point downward. The engines are part of the durable half, so an
  engine may import `values`, `vclock`, `errors`, `codec`, `clock`, `config`
  and its own layer, and may not import `replication`, `repair`, `antientropy`,
  `rebalance`, `migration`, `transaction`, `store` or `cli`.
  `python tools/check_arch.py` is the check, and it is green on the base commit.

Start with `docs/adr/ADR-0014-storage-boundaries.md` for where the lines are,
and `docs/incidents/` for what crossing them has already cost this store.
