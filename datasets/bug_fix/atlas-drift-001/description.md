# Restore the invariants of a sharded store

Atlas is a sharded, replicated, fenced key-value store. Its repository suite
is green, and yet a production cluster reports five different failure modes
that appear only when the subsystems meet:

* a write that goes out **after a rebalance** is answered from a replica the
  current plan does not name;
* a caller that holds a generation **the store does not hold** is accepted by
  the fencing check instead of refused;
* a **torn tail** on the log erases a transaction whose `COMMIT` frame is on
  disk;
* two **concurrent writers** are resolved to the smaller writer identifier,
  and repair writes that answer forward, making the divergence permanent;
* a counter that is incremented around a **snapshot** advances by two instead
  of one after a restart.

Each of the five is a small change in one module, and none of them is visible
in the repository suite, which is why the cluster reports them and the
`PYTHONPATH=src python -m pytest tests` run does not.

`SPEC.md` is the normative contract and `README.md` is the map. The five
rules that matter here are the ones `README.md` lists under *the five rules
everything else follows from*, and each failure above is one of those rules,
broken in the module that owns it:

1. durable `COMMIT` — the torn tail;
2. `CURRENT` as the publication decision — the snapshot;
3. the **exclusive** boundary — the replay window;
4. **fencing equality** — the generation check;
5. the **descending** tie-break — the convergence of concurrent writes.

The placement of the fifth failure is not in the module you would expect, and
the placement of the first is not either. `docs/incidents/` holds two hundred
notes about the cluster's past, and the two or three that name the rule you
need are written about the symptom rather than the module, so they are not
found by searching for the module name.

Use `tools/parity.py` to drive the store against a deliberately naive model.
It is the fastest way to see a divergence and the slowest way to understand
one, because the model knows three rules and the store has more than three.

Keep the public API, the wire format, the crash contract, and the repository
suite intact. The vendored v1 ring in `atlas/vendor` and the generated tables
in `atlas/tables.py` are not the write path and are not where the defects
live.
