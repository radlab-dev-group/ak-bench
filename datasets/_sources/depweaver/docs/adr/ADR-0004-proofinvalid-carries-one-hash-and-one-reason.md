# ADR-0004: `ProofInvalid` carries one hash and one reason

Status: accepted. Referenced by SPEC.md P4, P5.

## Context

`verify_proof` can fail for causes that have nothing to do with each other:
the proof was computed over a different canonical form (wrong order, wrong
marker rendering, build metadata left in), the catalog has moved since the
proof was made, a justification is missing or does not hold, the lockfile
does not satisfy the manifest at all. Early drafts had one exception class per
cause and a bag of attributes (`expected`, `actual`, `package`, `version`,
`clause`). Callers — the two tools, `Store.recall`, the session — grew
`except` ladders, and each ladder was wrong somewhere: INC-0002 was a tool
that caught the order exception, re-sorted, and re-ran into the stale-catalog
exception with the same hash on the screen, and the operator concluded the
re-sort had not worked.

## Decision

Every verification failure is one exception type, `ProofInvalid`, with
exactly two attributes:

* `hash` — the canonical digest (`lock_digest`) of the lockfile **as
  presented to the verifier**, recomputed by the verifier. Never the digest
  the proof claims, never the catalog digest, never a proof envelope checksum.
  It identifies the artefact on disk the operator is looking at; it is the
  same value `tools/relock.py --canonical` prints and `tools/verify_lock.py
  --expect` compares against.
* `reason` — one sentence, stable text per cause (SPEC P5), naming the package
  and version where there is one.

The message is `proof rejected for <hash>: <reason>`. The verifier stops at the
first failing check, in the fixed order of SPEC P4, so one call reports one
cause.

## Consequences

* Three different root causes present with the same exception type, the same
  hash shape and often the very same hash. Matching on `type(error)` or on
  `error.hash` cannot distinguish them; only `error.reason` can. Tools print
  the reason verbatim (`invalid <hash> <reason>`), and callers that need to
  branch must branch on the reason text.
* Fixing one cause and re-running can produce a failure that looks identical
  at a glance. This is a property of the design, not a bug in the fix: the
  verifier reports the *first* failing check, and a lockfile can have several
  things wrong with it. Read the reason after every re-run.
* `ProofUnavailable` (the prover could not build a proof) is a different
  class on purpose. It is raised at lock creation time, never by the verifier,
  and it is not a statement that the lockfile is wrong.
* `Store.recall` and `Store.invalidate` catch `ProofInvalid` only, treat every
  reason the same (remove the entry) and let anything else propagate.

## Rejected

* One class per cause. Rejected: see INC-0002; the ladders were the bug.
* A `causes: list` attribute reporting every failing check. Rejected: later
  checks are not meaningful when an earlier one fails (a justification cannot
  be checked against a stale catalog), so the list would mix facts with
  artefacts of the first failure.
* Putting the proof's claimed digest in the exception as a second hash.
  Rejected: two hashes on one line is how INC-0002 operators got the two
  confused in the first place.
