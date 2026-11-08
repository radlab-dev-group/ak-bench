# The generation the store does not hold

Atlas is a sharded, replicated, fenced key-value store. Its repository suite
is green, and yet a production cluster reports one failure mode that appears
only when a writer and the store disagree about how far they have each
advanced:

* a caller that holds a generation **the store does not hold** is accepted by
  the fencing check instead of refused, and the write it carries lands;

The defect is one line in the module that owns the generation check. The
documented invariant is that the strict check is an **equality**: an offer
below the held generation is refused, an offer above it is refused, and only
the offer that names exactly what the store holds is admitted. The change
that broke it made the check one-sided — it still refuses offers below —
which is why a review that looked only at the stale-peer path found nothing
wrong, and why the repository suite, which never offers a generation ahead,
stays green.

The configuration's mode is part of the contract, and it is worth knowing
what the mode used to mean before anyone changes it. The modes exist for
peers that are *behind*; the store's own number is never a suggestion that a
writer's larger number be honored.

`SPEC.md` is the normative contract and `README.md` is the map. The rule
that matters here is the one `README.md` lists under *the five rules
everything else follows from*: **fencing equality**. The check must be an
equality in the direction the documentation says, in the mode the
configuration carries.

`docs/incidents/` holds two hundred notes about the cluster's past. One or
two of them name this exact relaxation and the change that was tried and
reverted around it, and they are written about the symptom — writes
accepted, alerts silenced — rather than about the module, so they are not
found by searching for the module name. A third note in the corpus is about
a different check in a different module and reads, at a glance, like it is
about this one; it is the note that makes a plausible-looking fix plausible.

Use `tools/parity.py` to drive the store against a deliberately naive model.
It is the fastest way to see a divergence and the slowest way to understand
one, because the model knows three rules and the store has more than three.

Keep the public API, the wire format, the crash contract, and the repository
suite intact. The vendored v1 ring in `atlas/vendor` and the generated tables
in `atlas/tables.py` are not the write path and are not where the defect
lives.
