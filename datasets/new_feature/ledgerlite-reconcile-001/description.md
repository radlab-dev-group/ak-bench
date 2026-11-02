# Implement `reconcile` from its specification

`reconcile` in `src/ledgerlite/reconcile.py` is declared, documented and
tested, but its body raises `NotImplementedError`. Write it.

The full contract is in the module's docstring: what a statement line is, what
a candidate is, the two passes (the window and the reference), how ties are
broken, what is `unmatched`, what is `open`, and what `difference_cents`
means. Read it before writing a line of code; it is the specification, and the
evaluation measures against it.

## The short version

- A line claims exactly one candidate and a candidate is claimed by at most one
  line; an amount must be exactly equal, sign included.
- Pass 1 looks only inside `window_days`; pass 2 is reference-driven and the
  window does not apply.
- Lines are always considered oldest first; among candidates the closer, then
  earlier, then smaller-id booking wins.
- `open_candidates` are entries that still carry an unclaimed candidate;
  `difference_cents` is the sum of the amounts the statement could not place.

## Boundaries

- Implement it in `src/ledgerlite/reconcile.py`; the public API of
  `ledgerlite` stays as it is, and nothing else in the package changes.
- The function is pure: it reads the journal and the statement and returns a
  `Reconciliation`; calling it twice on the same input returns the same answer.
- Do not add third-party dependencies — the standard library is enough.
- The repository's own test suite (`pytest`) has to stay green.
