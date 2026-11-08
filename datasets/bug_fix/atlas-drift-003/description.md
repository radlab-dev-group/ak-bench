# The winner is the name, not the hour

Atlas is a sharded, replicated, fenced key-value store. Its repository suite
is green, and yet a production cluster reports one failure mode that appears
only when two writers meet at the same moment:

* two **concurrent writers** — versions that carry no causal order between
  them — are resolved to the smaller writer identifier, and the repair path
  writes that answer forward to every peer it meets, making the divergence
  permanent;

The defect is one comparison in the module that owns the tie-break. The
documented invariant is that the tie-break is the **descending** writer
identifier: of two concurrent versions, the greater writer identifier wins,
in one direction, for every reader and every repair, on every replica. The
change that broke it flipped the comparison, which is why a review that
read the rule out loud found nothing wrong, and why the repository suite,
which never meets two concurrent versions with different writers, stays
green.

The repair path is the amplifier, not the defect. Repair is correct to
write the chosen winner forward to a peer that holds the loser; a
convergence rule that depends on each replica remembering what it picked is
not a rule, it is a hope. The direction of the comparison is the whole
contract.

`SPEC.md` is the normative contract and `README.md` is the map. The rule
that matters here is the one `README.md` lists under *the five rules
everything else follows from*: the **descending** tie-break.

`docs/incidents/` holds two hundred notes about the cluster's past. One or
two of them name this rule — the winner is the name, not the hour — and
they are written about the symptom, a fork that survived a full repair
cycle, rather than about the module, so they are not found by searching for
the module name. A note in the corpus argues, at length and in detail, that
the ascending direction is the safer one, and it is the note that makes a
plausible-looking fix plausible; the note is about a different cluster, a
different era, and a mistake that has since been corrected.

Use `tools/parity.py` to drive the store against a deliberately naive model.
It is the fastest way to see a divergence and the slowest way to understand
one, because the model knows three rules and the store has more than three.

Keep the public API, the wire format, the crash contract, and the repository
suite intact. The vendored v1 ring in `atlas/vendor` and the generated tables
in `atlas/tables.py` are not the write path and are not where the defect
lives.
