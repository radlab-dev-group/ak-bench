# Restore convergence for replicas that agree through different histories

Atlas is a sharded, replicated, fenced key-value store. Its repository suite
is green, and yet a convergence pass stops with *shard N did not converge for
epoch E*, naming a key that every replica holds at the same generation and
the same value. Nothing is being retired. Repair runs, writes nothing useful,
and the next pass reports the same key.

Operators have seen this message before, during a retirement, and the fix
that was right then is in the incident log. The incident log is evidence of
what happened, not a rule about what to change: `CONTRIBUTING.md` states that
the decision records under `docs/adr/` outrank `SPEC.md`, which outranks
`README.md`, and that incident notes rank below all three. Check the
retirement rule against this cluster before applying it.

The key the pass names was written by two writers, and the two replicas that
disagree saw those two writers in opposite orders.

Keep the public API, the wire format, the crash contract, and the repository
suite intact. Do not edit the specification, the decision records or the
incident corpus to match the code.
