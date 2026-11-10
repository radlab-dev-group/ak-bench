# ADR-0002: Proofs of solution are verified offline, without the solver

Status: accepted. Referenced by SPEC.md P3, P6, P7.

## Context

The obvious way to check that a lockfile is "still right" is to run the
solver again and compare. We did that for a year (`Session.replay`). It has
three costs we stopped being willing to pay.

1. **It is not a check of the lockfile; it is a check of the solver.** When a
   replay differs, nobody can say whether the lockfile was wrong or the solver
   changed. The eight-regression history of `resolver`, `propagation`,
   `candidates`, `learning` and `trail` (SPEC.md, "Search invariants") made
   this a weekly question.
2. **It is as expensive as the original solve.** Verification happens on
   every install and in every CI job; solving happens once per lock update.
   For the large generated catalogs a replay is seconds; a verification should
   be milliseconds.
3. **It needs the solver's environment.** Replay needs the learned-clause
   machinery, the candidate cache and the trail. A deployment host that only
   installs should not need any of that, and must not be able to be talked
   into a different answer by a cache.

## Decision

A **proof of solution** is a certificate produced once, when the lock is
created (`prove`, `Session.prove`, `tools/relock.py --prove`), and checked any
number of times by `verify_proof`, which:

* re-derives everything it needs from the manifest, the lockfile and the
  catalog — active clauses, locked extras, the preferred set — and trusts
  nothing in the proof but the claims it then checks;
* checks validity with `validation.validate`, which is already independent of
  the search implementation;
* checks, for every catalog version the policy would have preferred, that the
  proof's justification *holds*: a pin, a Python requirement, a yank, a
  prerelease rule, an active clause whose range or extras reject the version,
  or a conflict between the excluded release's own requirements and the
  solution (one step, or nested through a package that is not in the
  solution, at most four levels);
* constructs no `Resolver` and imports nothing from `resolver`,
  `propagation`, `candidates`, `learning` or `trail`.

The prover is allowed to be incomplete: when it cannot find a justification of
the shapes above it raises `ProofUnavailable`, and the lock is published
without a proof — which `tools/verify_lock.py` reports as exit 2, not as a
verification failure. A proof that *is* produced is always checkable.

## Consequences

* A verification failure is about the lockfile, the catalog or the proof,
  never about the solver's internals. `ProofInvalid` says which (ADR-0004).
* The justification kinds are a closed list (SPEC P3). Adding a kind is a
  SPEC change and a new ADR, not a patch.
* Because the verifier re-derives the active clauses from the lock's target and
  the *locked* extras, a proof is bound to one target; a lockfile reused for
  another target has no valid proof, which is what we want.
* The nested `candidates` justification is the only place the verifier walks
  the catalog beyond the chosen releases. It is bounded by depth 4 and by the
  spec of the enclosing dependency; it never enumerates the catalog.

## Rejected

* Re-running the solver with a decision budget as the "verification".
  Rejected: all three costs above remain, and a budget turns a verification
  into a probabilistic one.
* Signing lockfiles. Rejected as orthogonal: a signature says who produced the
  file, not that the file is a solution.
