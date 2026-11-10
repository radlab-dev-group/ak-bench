# Restore the quorum and convergence rules of a sharded store

Atlas is a sharded, replicated, fenced key-value store. Its repository suite
is green, and yet a cluster that is retiring one of its replicas reports four
failure modes that appear only when the subsystems meet:

* a write that **only one healthy replica** acknowledged is reported as
  committed, because the replica being retired acknowledged it too;
* a convergence pass run during the same retirement stops with *shard N did
  not converge for epoch E*, naming a key that the replica being retired
  holds at an older generation and that nothing brought level;
* a replica that was cut off and came back is **repaired into a generation
  nobody wrote**: after one read it is one generation ahead of the others, the
  next read moves the others past it, and the next write is refused by the
  fence with *offered generation 3 but the current generation is 2*;
* a worker that fell behind **takes the key's lease sideways**: its commit
  at a generation already on record is accepted instead of refused, and the
  lease afterwards names a generation the store has moved past.

Each of the four is a small change in one module. They come in two pairs,
and the pairs are the point: for each pair, the change that makes the first
symptom go away brings the second one back with the same exception and the
same message, and the change that makes the second go away brings the first
back. Oscillating between the two is what the cluster's operators did for a
day. The resolution is a rule, not a compromise, and the rule for each pair
is written down in exactly one place.

`CONTRIBUTING.md` states where the truth lives: the decision records under
`docs/adr/` outrank `SPEC.md`, which outranks `README.md`, and the notes under
`docs/incidents/` are evidence of what happened, not rules about what should.
Two of the recent incident notes about these symptoms name a module that is
not at fault, as a real incident log would. The decision records are written
about symptoms and invariants, not about modules, so they are not found by
searching for the module name.

Hidden tests drive the cluster through partition, repair, drain and rebalance
in fixed orders, using the store's deterministic crash points where a crash
is part of the scenario. Public tests state the four complaints as the
operators phrased them.

Keep the public API, the wire format, the crash contract, and the repository
suite intact. Do not edit the specification, the decision records or the
incident corpus to match the code. The vendored v1 ring in `atlas/vendor` and
the generated tables in `atlas/tables.py` are not the write path and are not
where the defects live.
