# ADR-0014: The store's layers import downward only

- Status: accepted
- Date: 2026-11-12
- Concerns: every module under `src/atlas/`, `tools/check_arch.py`,
  `SPEC.md` 1, 3, 11

## Context

The store grew by accretion: each feature took the code it needed and put it
where it was working, and for a long time that was good enough, because the
features were small and the imports they drew were the obvious ones. The
obvious import is also the one that is hard to see later. `atlas.repair`
importing `atlas.replication` is a design statement — repair is the part of
the protocol that talks to replicas — and it is true. `atlas.storage`
importing `atlas.replication` is the same line in the file and a different
statement: the durable half of the store now knows about the protocol, and
the storage layer can no longer be tested without standing up a cluster.

The boundary nobody draws is the one that has to be enforced. A code review
catches the violation that is in front of it; it does not catch the one that
is three imports deep in a refactor that moves a helper to the layer where
the helper's callers are. The helper's new home looks reasonable on the
commit, and the import that is now the wrong way up is one line nobody
reads.

## Decision

The modules are grouped into five layers, and an import may go only from a
higher layer to a lower one:

1. **Foundation.** `errors`, `values`, `vclock`, `registry`, `audit`,
   `lineage`, `schema`, `tables`, `codec`. The data model and the things it
   depends on; nothing in this layer imports anything else in the store.
2. **Configuration and placement.** `clock`, `config`, `membership`, `ring`,
   `placement`, `faults`. Who is in the cluster, where a key lives, and the
   deterministic faults a scenario injects.
3. **The durable half.** `wal`, `snapshot`, `memtable`, `storage`,
   `retention`, `evolution`. One shard's state on disk and in memory. This
   layer does not know that other shards exist.
4. **The protocol.** `fencing`, `repair`, `replication`, `antientropy`,
   `migration`, `rebalance`, `transaction`, `cache`. The rules that move
   state between shards.
5. **The public surface.** `store`, `cli`, `compat`. The API a caller sees
   and the command line that drives it.

`tools/check_arch.py` reads the layer map and reports every import that goes
upward; the exit code is 0 when the tree respects the layers and 1 when one
does not, so a violation fails a build the same way a failing test does. The
map lives in the tool and a `--rules` document can replace it, because the
boundary is a property of the design being built and not of the checker.

## Consequences

- A module that needs a helper from a higher layer moves the helper down, or
  passes the value in as an argument. Both are more honest than the import.
- A test that wants the storage layer alone can now have it, because the
  storage layer stops at its own edge. That is what the tests for a pluggable
  storage engine need: an engine that can stand up without a cluster is the
  only engine that can be swapped.
- The `vendor` ring and `compat` are on the public surface, not in the
  foundation, because they are v1 shims: they exist for callers that still
  compute placement the old way, and they are not on the write path.
