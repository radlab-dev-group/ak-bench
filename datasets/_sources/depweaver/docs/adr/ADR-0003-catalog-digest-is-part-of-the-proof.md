# ADR-0003: The catalog digest is part of the proof and is the only cache invalidation signal

Status: accepted. Referenced by SPEC.md P1, P4, P8.

## Context

A proof justifies exclusions by pointing at catalog facts: "version 2.0.0 is
yanked", "every version of `mid` matching `>=2` requires `core ==2`". Those
facts are true of one catalog snapshot. Against another snapshot the same
proof may be false in a way the verifier cannot see: a catalog that gained
`mid 2.1.0` without the `core ==2` requirement makes the `candidates`
justification incomplete, and a verifier that only checks the clauses it was
handed will happily accept it. INC-0003 is exactly this — a cached resolution
served for three weeks after the catalog it was solved against had moved.

The same question arises for the resolution cache in `store.Store`. The cache
key was the manifest fingerprint, which does not change when the catalog does.
We tried adding a time-to-live, then a "dirty" flag set by the catalog editor.
Both were wrong in the same way: they described when the *cache* thought it
was stale, not whether the *solution* was.

## Decision

* The proof payload carries `catalog`, the fingerprint of the repository
  snapshot the proof was produced under (`Repository.fingerprint`, which is
  order-independent and covers complete metadata).
* `verify_proof` compares it with the fingerprint of the catalog it is given
  and rejects with `catalog digest is stale` before it looks at a single
  justification. The comparison is exact: there is no "compatible change"
  notion, because the verifier cannot know which changes are compatible
  without being a solver (ADR-0002).
* The resolution cache has no time-to-live and no dirty flag. `Store.recall`
  and `Store.invalidate` verify the stored proof against the catalog the
  caller presents; a proof that fails for any reason removes the entry. The
  catalog digest check is therefore sufficient to invalidate a cached
  resolution, and nothing else is needed or allowed to.

## Consequences

* Any catalog change — a new release of an unrelated package, a corrected
  `requires_python` on something nobody selects — invalidates every proof and
  every cached resolution. This is deliberate. Re-proving is cheap
  (`tools/relock.py --canonical --prove` on an unchanged solution produces the
  same lock digest and a new proof); serving a stale solution is not.
* A proof is portable only together with the catalog document it names. The
  guide tells you to keep the catalog JSON next to the lock and the proof.
* The stale-catalog rejection has the same exception type and hash shape as a
  wrong canonical order and a missing clause (ADR-0004). The reason string is
  how you tell them apart.

## Rejected

* Per-package catalog digests ("only the packages the proof mentions"). Rejected:
  the `candidates` justification depends on the *absence* of versions, which a
  per-package digest of the mentioned versions cannot capture.
* Time-to-live. Rejected: it measures time, not change.
* A dirty flag set by `catalog.Editor`. Rejected: catalogs also change by
  being replaced wholesale (`Repository.read`), which no editor sees.
