# Repair the resolver's branch and context protocol

The repository suite passes, but the resolver fails on multi-stage dependency
graphs and when reused for another environment or partial update. Symptoms
include false unsatisfiability, missing optional dependencies, unexpected pin
changes and results that depend on earlier solve calls or declaration order.

Read `SPEC.md`. Diagnose the protocol across the trail, fixed-point propagation,
constraint provenance, learned incompatibilities, candidate cache and lock
policy. The task contains eight related regressions; fixing a single obvious
counterexample is insufficient. Each has an independent hidden counterexample,
and mixed scenarios combine them.

Restore complete rollback, monotone feature activation, owner-relative marker
evaluation, sound contextual learning and isolation of request-specific state.
Keep deterministic candidate preferences and hard pins for packages outside the
explicit update set. A returned solution must satisfy the complete active
closure; a failed request must not poison a subsequent valid request.

Keep the solver architecture operational. Disabling learning/caching or replacing
search with enumeration is outside the task. The evaluator checks small cases
against an independent exhaustive model and includes larger families with many
irrelevant candidate combinations. Preserve public formats, structured errors,
metadata integrity, existing tests and standard-library-only execution.
