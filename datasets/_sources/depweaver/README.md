# Depweaver

An offline semantic-version dependency resolver with optional features,
environment markers, partial lockfile updates, conflict learning, backjumping,
graph analysis and package metadata tooling. It uses only Python 3.12's standard
library. Read SPEC.md for the observable search and rollback contract.

The source project is correct before benchmark mutations. Ordinary repository
tests exercise versions, metadata and straight-line resolution. The benchmark
regression spans cooperating solver modules and requires harder scenarios than
those local tests. Keep all public APIs, formats and contracts intact.

```
PYTHONPATH=src python -m pytest tests
PYTHONPATH=src python -m depweaver.cli --help
```

No external registry, network, package installation, wall clock or subprocess
solver is required. Do not replace the resolver with enumeration over the full
repository Cartesian product: generated stress tests include large irrelevant
domains, cycles and conflict-driven backtracking. Learned state and caches must
remain semantically sound across repeated solve calls on one Resolver.

Project tooling is part of the compatibility surface. `requirements` and
`manifest` parse requirements, TOML groups and target profiles; `metadata` imports
offline Core Metadata. `catalog` edits immutable metadata snapshots using
reversible revisions. `session` records and replays solves, while `workspace`
publishes project lock updates transactionally and `matrix` combines targets.
`validation` checks results independently of the search implementation.

`explain`, `constraints` and `reports` expose provenance, deletion-minimal root
conflicts, direct candidate diagnostics, update impact and graph summaries.
`planner` creates reversible environment plans; `audit` matches offline
advisories; `inventory` exports checksummed software inventories. `wheels` checks
compatibility tags and RECORD integrity without installing anything. `store`
provides verified immutable artifact blobs, indexes and explicit garbage
collection. These modules consume the resolver's public records and make its
state isolation, feature closure and lock correctness observable to callers.
