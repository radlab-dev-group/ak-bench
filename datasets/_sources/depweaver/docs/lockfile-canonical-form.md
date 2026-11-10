# Lockfile canonical form and proofs of solution

This is the guide. The normative text is SPEC.md, section "Lockfile canonical
form and proofs"; the reasons are in `docs/adr/`; the symptoms that led to the
design are in `docs/incidents/`. If this guide and an ADR disagree, the ADR is
right and this guide has a bug (see CONTRIBUTING.md).

## What the feature is

A lockfile body (`lockfile.Lockfile`) lists packages alphabetically and is
checksummed. That checksum tells you the file was not corrupted. It does not
tell you that two lockfiles produced from differently spelled metadata are the
same solution, and it does not tell you that the solution is still the one
the solver would produce against the catalog you have now. Two things fix
that:

1. the **canonical form** — a JSON document derived from a resolution whose
   bytes depend only on *what was solved*, not on how the metadata was
   written; its SHA-256 is the **lock digest** (`canonical.lock_digest`);
2. the **proof of solution** — a certificate (`proofs.Proof`) that names the
   catalog snapshot, the lock digest, the chosen releases in canonical order
   and one justification for every catalog version the policy preferred but
   the solution does not contain; `proofs.verify_proof` checks it offline.

## The canonical order (read this twice)

The intuitive order — alphabetical by name — is **not** the canonical order.
The canonical order is the install order (ADR-0001). Rows are sorted by

    (layer, normalised name, version, extras tuple)

where:

* **layer** is the height of the package in the *active* dependency graph of
  the solution after cycles have been collapsed. A package that actively
  depends on nothing selected is in layer 0. A package is one layer above the
  highest package it actively depends on. Every member of a dependency cycle
  shares the cycle's layer.
* an **active edge** from `P` to `Q` exists when `P`'s locked release declares
  a dependency on `Q`, `Q` is in the solution, and the dependency's marker
  holds in the lock's target evaluated with `P`'s *locked* extras. Edges to
  packages outside the solution do not exist. Self-edges do not exist.
* **normalised name** is `model.normalize`; **version** compares semantically
  (so `1.10.0` sorts after `1.9.0`) and renders without build metadata;
  **extras tuple** is the locked active extras, normalised and sorted.

Worked example. `app 1.0.0` depends on `core ==1` and on
`Zeta_Lib >=1; sys_platform == "linux"`; `zeta-lib 1.0.0` depends on
`core <3`. Alphabetical order is `app, core, zeta-lib`. Canonical order is

    core 1.0.0        layer 0
    zeta-lib 1.0.0    layer 1
    app 1.0.0         layer 2

## Marker rule M

Markers inside the canonical rows are re-rendered, never copied:

| written                                                         | canonical                                              |
|-----------------------------------------------------------------|--------------------------------------------------------|
| `sys_platform == 'linux'`                                       | `sys_platform == "linux"`                              |
| `python_version >= "3.8"`                                       | `python_version >= "3.8.0"`                            |
| `python_version in "3.11,3.10"`                                 | `python_version in "3.10,3.11"`                        |
| `sys_platform == "linux" and extra == "fast"`                   | `extra == "fast" and sys_platform == "linux"`          |
| `a == "1" and (b == "2" or c == "3")` (field names abbreviated) | `(b == "2" or c == "3") and a == "1"` — `or` under `and` is parenthesised |
| `(a == "1" and b == "2") and c == "3"`                          | `a == "1" and b == "2" and c == "3"` — chains flatten  |
| `a == "1" or a == "1"`                                          | `a == "1"` — duplicates collapse                       |

Operands of a chain are sorted by their rendered text, so `(` sorts before any
letter and a parenthesised `or` group comes first in an `and` chain.

## The row and the digest

Each row is

    {"layer", "name", "version", "extras", "provides", "requires",
     "requires_python", "yanked", "artifact"}

`extras` are the locked active extras, `provides` the release's declared
extras, `requires` the release's dependency declarations re-rendered
(`{name, spec, extras, marker}`) and sorted by `(name, marker, spec, extras)`,
`artifact` the release digest or `""`. The document is
`{"version": 1, "target": ..., "packages": [...]}` and the lock digest is the
SHA-256 of `model.canonical(document)`.

Permuting the order of dependencies in the catalog, writing a marker with
single quotes, or adding `+build.7` to a version must not change the digest.
Changing a selected version, an active extra or the target must.

## Proofs: what is inside and what is checked

A proof payload is `{digest, catalog, manifest, chosen, exclusions}` wrapped in
a codec envelope of kind `proof`. `chosen` is the canonical order. `exclusions`
has one entry for every version in the **preferred set** of every chosen
package — all versions above the chosen one (below it under `prefer_lowest`),
or every other version when the package is pinned. Each entry carries exactly
one justification; the kinds and their meaning are SPEC P3.

`verify_proof(manifest, lockfile, proof, catalog)` checks in this order and
stops at the first failure:

1. `proof.digest == lock_digest(lockfile)` — else `canonical digest mismatch`;
2. `proof.chosen` is the canonical order — else `chosen releases are not in
   canonical order`;
3. `proof.catalog == catalog.fingerprint` — else `catalog digest is stale`;
4. `proof.manifest == manifest.fingerprint`;
5. `validation.validate` reports nothing;
6. every preferred version has one justification and it holds — else
   `missing justification for <name> <version>` or `justification does not
   hold for <name> <version>`;
7. no exclusion names a version outside the preferred set.

Every failure is one `ProofInvalid(hash=<lock digest of the lockfile as
presented>, reason=<one string>)`. The hash is never the digest the proof
claims (ADR-0004). Three completely different root causes — a wrong canonical
order, a stale catalog, a missing clause — therefore raise the same exception
type with the same hash shape. Read the reason. Do not fix the first one you
guess and re-run; the second cause produces the same signature (INC-0002).

## The procedure (playbook)

Lockfiles under version control are produced and checked with the repository
tools, not by hand. Both tools take a catalog document (`Repository.document`
as JSON) and a request document (`codec.request` shape).

    python tools/relock.py --catalog catalog.json --request request.json \
        --output lock.json --canonical --prove
    python tools/verify_lock.py --catalog catalog.json --request request.json \
        --lock lock.json --expect <digest printed by relock>

`relock.py` prints `lock <path>`, then with `--canonical` the line
`digest <64 hex>`, then with `--prove` `proof <path>` and
`proof-sha256 <64 hex>`. The proof is written next to the lockfile as
`<stem>.proof.json`. `--prove` without `--canonical` exits 2. `verify_lock.py`
prints `ok <digest>` and exits 0, or `invalid <hash> <reason>` and exits 1, or
`digest mismatch: expected <a> got <b>` and exits 1 when `--expect` disagrees,
or exits 2 with a hint when there is no proof to verify. Keep the digest
printed by `relock.py`; you need it again at the end to call `verify_lock.py
--expect`.

A lockfile without a proof next to it is not reproducible by this project's
definition, however green the solver is.

## Caching

`store.Store` keeps cached resolutions under `resolutions/<manifest
fingerprint>.json` as envelopes of kind `cached-resolution` holding the
manifest, the lockfile and the proof. `recall(manifest, catalog)` hands a
lockfile back only after its proof verifies under *that* catalog; otherwise it
deletes the entry and returns `None`. `invalidate(catalog)` sweeps every entry
the same way and returns what it removed. There is no time-to-live and no
separate "dirty" flag: the catalog digest inside the proof is the only
invalidation signal (ADR-0003, INC-0003).
