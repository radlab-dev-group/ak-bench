# Resolution and repair contract

## Metadata

Names and extras normalize runs of dash/underscore/dot to a lowercase dash.
Release identities are normalized name plus semantic version (build metadata
does not change ordering/equality). SemVer prerelease numeric segments compare
numerically. Specs are ORs (`||`) of comma-conjoined comparisons: ==, !=, <,
<=, >, >=, caret, tilde and trailing wildcard equality. Version ranges concern
precedence; prerelease eligibility is a separate policy decision.

Dependency(name, spec='*', extras=(), marker='') specifies a target package,
required range and optional features to ACTIVATE ON THAT TARGET package.
Release declares available extras, dependencies, requires_python, yanked state
and an optional artifact digest. Repository metadata is immutable during one
solve. Fingerprints include complete metadata and are order-independent at
repository/release insertion level. Dependency declaration ordering must never
change the selected result.

## Activation and markers

Start from root requirements whose markers hold. Track the UNION of every
active requirement's requested extras per target package. Re-expand a selected
release whenever its active extra set grows, even if it was already expanded
at an earlier fixed-point iteration. Keep cyclic propagation finite by tracking
all relevant expansion context. Only reachable active dependencies participate.

A dependency marker evaluates in request.target and the extras of the package
DECLARING that dependency, not the target dependency's extras. With no extra,
evaluate once with extra=''; otherwise evaluate once per active extra and OR
the answers. Supported fields: python_version, sys_platform, platform_machine,
implementation_name and extra. `and` binds tighter than `or`; parentheses work.
Strings are quoted. Python versions compare numerically; other fields compare
lexically. `in` and `not in` compare against comma-separated exact strings.
Markers must be parsed, never passed to eval/exec.

## Domains, preferences and locks

A candidate must satisfy ALL active ranges, support ALL requested extras, and
support target Python. Yanked releases are excluded unless policy allows them
or that exact version is already locked. Prereleases are excluded unless policy
allows them, an active range explicitly mentions a prerelease, or that exact
version is already locked. Locked packages outside request.update are hard
pins WHEN REACHABLE. Pins do not activate otherwise unreachable packages.
Only explicitly updated package names may move; updating one package does not
implicitly unlock every other pin. Unsupported pins make the request unsatisfiable.

Choose an unresolved package with the smallest eligible domain, ties by
normalized package name. Try semantic versions from highest to lowest, or
lowest to highest with prefer_lowest. Return the first complete valid result
under that decision ordering. Safe pruning must preserve that result. A solution
contains exactly the reachable closure, in package-name order, with the final
union of extras. SearchLimit is distinct from Unsatisfiable.

## Search invariants

Each trail level holds one exact package/version decision. rollback(saved)
discards EVERY decision above saved from both the decision list and selected
map. No dependency, extra, expansion key or constraint introduced by a discarded
branch may constrain a sibling branch. Recomputing closure is allowed.

Conflict explanations contain exact decisions sufficient to imply the conflict,
including all parent requirement/feature provenance needed for that implication.
An incompatibility clause forbids the conjunction of its members, not every
member separately. Never drop contextual decisions when learning. A conflict
independent of the current decision can return past that decision; otherwise
try the next candidate before declaring its parent impossible. A solver may use
a more conservative valid explanation, but must remain complete and preserve
the preference rule. Learned incompatibilities are scoped to ONE solve request.

Cache keys must distinguish repository metadata, package, active ranges, union
of extras, target environment, policy, pins and update set. A cache hit cannot
change satisfiability or the preferred result. Reusing one Resolver across
different roots, extras, targets or partial updates must agree with fresh solvers.
Do not disable caches/learning/backjumping as the repair: keep each mechanism
operational and sound. Repository tests and the integrity suite inspect these
mechanisms and compare complete solve behavior.

## Errors and integrity

Missing metadata/versions, impossible ranges, unsupported extras and conflicts
raise Unsatisfiable with a structured Conflict, not KeyError, recursion errors
or fabricated partial results. A failed solve leaves the repository unchanged
and cannot poison a later solve. Invalid input metadata raises ValueError.
Lockfile publication remains checksummed and target-bound. Validation must keep
checking dependency closure, feature closure, all pins and metadata integrity.

The task contains eight related regressions. Hidden tests have a separate
counterexample for each and mixed generated traces. Small repository results
are compared with an independent exhaustive oracle. Larger families require
constraint-directed search; do not special-case their package names.

## Lockfile canonical form and proofs — declared, not implemented

This section is normative. `src/depweaver/canonical.py`, `src/depweaver/proofs.py`
and the three cache methods of `store.Store` declare the surface and raise
NotImplementedError. The procedure that exercises them is
`tools/relock.py --canonical --prove` followed by `tools/verify_lock.py`; the
guide is `docs/lockfile-canonical-form.md`, the reasons are `docs/adr/`.
Where this section and an ADR disagree, the ADR wins (CONTRIBUTING.md).

### Canonical form

* **C1 Normalisation.** Package and extra names normalise as in Metadata.
  Versions render without build metadata. Extras are normalised,
  deduplicated and sorted.
* **C2 Markers (rule M).** A comparison renders as `field op "literal"` with
  the literal as a double-quoted JSON string. A `python_version` literal of an
  ordered or equality comparison is coerced to three components (`"3.8"` ->
  `"3.8.0"`). The literal of `in` / `not in` is split on `,`, deduplicated,
  sorted and joined with `,` (segments are not trimmed). `and` and `or` chains
  are flattened; operands are rendered, deduplicated and sorted
  lexicographically by rendered text, then joined with ` and ` / ` or `. An
  `or` directly beneath an `and` is parenthesised; nothing else is. The empty
  marker renders as the empty string.
* **C3 Active edges.** Selected `P` actively depends on selected `Q` when a
  dependency declared by `P`'s locked release names `Q` and its marker holds in
  the lock's target under `P`'s locked extras. Self-edges are ignored.
  Dependencies on packages outside the solution are not edges.
* **C4 Layers.** Condense the active graph by strongly connected components. A
  component with no edge to another component has layer 0; otherwise its layer
  is one more than the highest layer it points to. Members of one cycle share
  a layer.
* **C5 Package order.** Rows are ordered ascending by the tuple
  `(layer, normalised name, version, extras tuple)`, versions by semantic
  ordering. This is the install order. It is deliberately not the alphabetical
  order the lockfile body uses (ADR-0001).
* **C6 Rows and digest.** A row is
  `{layer, name, version, extras, provides, requires, requires_python, yanked, artifact}`
  where `extras` are the locked active extras, `provides` the release's declared
  extras, `requires` the canonical dependency rows of the release sorted by
  `(name, marker, spec, extras)`, and `artifact` the release digest or `""`.
  The canonical document is `{"version": 1, "target": <target document>,
  "packages": [rows]}`. `lock_digest` is the SHA-256 hex digest of the
  canonical JSON (`model.canonical`) of that document. Two resolutions with
  the same selected releases, extras and target have the same digest whatever
  the order their metadata was declared in, however their markers were
  spelled and whatever build metadata their versions carried.

### Proofs of solution

* **P1 Payload.** A proof is `{digest, catalog, manifest, chosen, exclusions}`:
  the `lock_digest`, the catalog (repository) fingerprint, the request
  fingerprint, the `(name, version)` pairs of the solution in canonical order,
  and one exclusion per preferred-but-unchosen catalog version. Transport is a
  codec envelope of kind `proof`; `Proof.load` rejects anything else.
* **P2 Preferred set.** For chosen `P@v`: when `P` is pinned (locked and not in
  `update`) every other catalog version of `P`; otherwise every catalog version
  above `v` (below `v` under `prefer_lowest`). Each member has exactly one
  exclusion `{name, version, justification}`.
* **P3 Justifications.** `justification.kind` is one of:
  `pin` (another version is pinned); `python` (requires_python rejects the
  target); `yanked` (yanked, policy forbids, not the same lock); `prerelease`
  (prerelease, policy forbids, not the same lock, no active clause for the
  package allows prereleases); `range` / `extras` with `{parent, dependency}`
  naming an active clause for the package — a root whose marker holds (parent
  `null`) or a dependency of a chosen release whose marker holds under that
  release's locked extras — whose spec rejects the version (`range`) or whose
  extras the release lacks (`extras`); `conflict` with `{dependency}` declared
  by the excluded release and active under the package's locked extras, and
  either `chosen: [name, version]` (the chosen release of the dependency's
  target fails its spec or lacks its extras) or `candidates: {version:
  justification}` (the target is not in the solution and every catalog version
  matching the spec is itself justified, recursively, with the enclosing
  dependency counting as an active clause for it). Nesting depth is at most 4.
* **P4 Verification order.** `verify_proof(manifest, lockfile, proof, catalog)`
  checks, in this order, and stops at the first failure: the proof digest
  equals `lock_digest(lockfile)`; `chosen` equals the canonical order; the
  proof catalog equals `catalog.fingerprint`; the proof manifest equals
  `manifest.fingerprint`; `validation.validate` reports nothing; every
  preferred version has exactly one justification that holds — packages in
  name order, versions ascending, so the reason names the lowest offending
  version of the first offending package; no exclusion names a version
  outside the preferred set.
* **P5 One hash, one reason.** Every failure is `ProofInvalid(hash=..., reason=...)`
  with `hash` the `lock_digest` of the lockfile *as presented* — never the
  digest the proof claims — and a single reason string. The message is
  `proof rejected for <hash>: <reason>`. The reasons for the first three checks
  are `canonical digest mismatch`, `chosen releases are not in canonical
  order` and `catalog digest is stale`; a missing clause is `missing
  justification for <name> <version>` (ADR-0004).
* **P6 Offline.** Verification runs no solver: it constructs no `Resolver` and
  calls nothing in `resolver`, `propagation`, `candidates`, `learning` or
  `trail` (ADR-0002).
* **P7 Generation.** `prove(catalog, manifest, resolution)` validates the
  resolution first and raises `ProofUnavailable` when it is invalid or when no
  justification of the kinds in P3 exists for a preferred version.
  `Session.prove(name)` proves a record under the session's catalog.
* **P8 Cache invalidation.** `Store.remember(manifest, lockfile, proof)` writes
  `resolutions/<manifest fingerprint>.json` as a codec envelope of kind
  `cached-resolution` with `{manifest, lock, proof}`. `Store.recall(manifest,
  catalog)` returns the cached lockfile only after its proof verifies under
  `catalog`; when it does not, the entry is removed and `None` is returned.
  `Store.invalidate(catalog)` removes every cached resolution whose proof fails
  under `catalog` and returns their manifest fingerprints. A changed catalog
  digest is therefore sufficient to invalidate (ADR-0003).
