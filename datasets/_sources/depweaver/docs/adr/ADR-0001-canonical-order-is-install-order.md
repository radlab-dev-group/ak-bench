# ADR-0001: The canonical lockfile order is the install order, not the alphabetical order

Status: accepted. Supersedes nothing. Referenced by SPEC.md C3–C5.

## Context

The lockfile body sorts packages by name because `Lockfile.load` rejects
anything else, and because a name-sorted list is easy to diff by eye. When we
started hashing lockfiles to detect "same solution, different spelling"
(INC-0001) the first digest was simply the SHA-256 of the name-sorted body.
It had two problems.

First, the body carries metadata exactly as the catalog spelled it. The same
dependency declared as `Zeta_Lib>=1; sys_platform=='linux'` by one catalog
export and as `zeta-lib >=1.0.0 ; sys_platform == "linux"` by another gave two
digests for one solution. That is a normalisation problem and is solved by
rule M and the row shape, not by the order.

Second — the reason this ADR exists — a name-sorted document is the wrong
*shape* for the consumers of the digest. The digest is checked right before
an installer streams the lockfile, and the installer wants dependencies
before dependents. Rendering one document for hashing and another for
installing means the hash does not cover what gets installed. We tried
hashing both; INC-0001 is what happened when the two drifted.

## Decision

The canonical form orders rows by `(layer, normalised name, version, extras
tuple)`, where `layer` is the height of the package in the condensation of
the *active* dependency graph of the solution: leaves are layer 0, a package is
one layer above the highest package it actively depends on, members of a cycle
share a layer. Within a layer the order is by normalised name, then semantic
version, then the sorted tuple of locked active extras.

"Active" means: the edge is a dependency of the locked release whose marker
holds in the lock's target under the *locked extras of the depending
package*. Edges to packages that are not in the solution are not edges.

## Consequences

* The canonical order is not what a reader expects. `core` comes before `app`
  because `app` needs `core`, even though `a` < `c`. The guide says so in its
  first paragraph on ordering, and `verify_proof` rejects a proof whose
  `chosen` list is alphabetical with the reason `chosen releases are not in
  canonical order`.
* The order is a function of the solution alone. No catalog, manifest or
  solver state is needed to compute it, so the digest can be recomputed by a
  tool that has only the lockfile.
* Adding an *inactive* dependency (marker false on the lock's target) to a
  release changes the row (its `requires` list) and therefore the digest, but
  does not change the layer. Adding an active one may move the package up a
  layer and reorder the document. Both are correct: in both cases the solution
  changed.
* Ties by name inside one layer make the order total. Two distinct releases
  of one package cannot be in one solution (`Lockfile.load` rejects
  duplicates), so the version and extras components exist for completeness of
  the key and for the row's identity, not to break ties in practice.

## Rejected

* Alphabetical by name (the body order). Rejected for the reasons above; kept
  for the body because it is the compatibility surface of `Lockfile`.
* Depth from the roots (distance from a manifest root). Rejected because it
  depends on the manifest, which is not in the lockfile, and because a package
  reachable from two roots at different distances has no single depth.
* Topological order with name tie-break but without layers. Rejected because
  it is not unique: many topological orders exist for one graph, and the
  tie-break rule would have had to be stated procedurally (a specific
  algorithm) rather than as a sort key. Layers give a sort key.
