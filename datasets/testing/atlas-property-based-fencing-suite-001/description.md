# Four defects are in the wild and not one test sees them

The atlas suite exercises fencing call by call: grant, check, release. Every one
of those calls behaves when you hold it still. The four defects below are
behaviour that only shows up across a sequence of calls, which is why they ship,
and why your job is a model rather than more assertions.

Write `tests/test_fencing_stateful.py`: a seeded, stateful suite that runs a
random-but-reproducible sequence of lease take-overs, write checks, convergence
decisions and compare-and-set writes against the store, and checks every answer
against a model of what the rules say. It has to pass on this repository exactly
as it is, and it has to fail — loudly, and in under a minute — on each of the
four mutants described below.

## The drift family

The hidden harness applies each of these to a copy of the repository and runs
your suite. It does not tell you which one fired.

| id | module | what changes |
| --- | --- | --- |
| `drift-001` | `src/atlas/fencing.py` | the lease book stops refusing a generation equal to the one on record |
| `drift-002` | `src/atlas/fencing.py` | the strict generation check stops refusing an offer *ahead* of the record |
| `drift-003` | `src/atlas/repair.py` | the concurrency tie-break settles for the smallest writer identifier |
| `drift-004` | `src/atlas/storage.py` | a compare-and-set write stops refusing an offer for a generation the store never had |

Each is one comparison. None of them changes what a single call does when the
call is the only thing that has ever happened to the key — which is exactly why
the current suite is green with all four in place.

## The rules the model has to encode

- `README.md` rule 4 — the generation check is an equality under `strict`, in
  **both** directions.
- `README.md` rule 5 — concurrent writes are settled by the **greatest** writer
  identifier, and every replica has to reach the same winner.
- `SPEC.md` §5.1 and §5.4 — what `strict` and `permissive` each mean, and that a
  commit marker is checked exactly like a write.
- `docs/adr/ADR-0003-a-version-is-minted-once.md` — the lease book moves forward
  only; a generation is granted once.
- `docs/incidents/INC-1201` … `INC-1204` — one symptom each, all of them found
  too late.

## What the harness does

1. Runs your `tests/test_fencing_stateful.py` against the repository unchanged:
   the exit code has to be 0, with at least one test that actually asserts
   something (no skips, no `xfail`, no empty module).
2. Runs it again against a copy with one mutant applied, four times: every run
   has to fail, and has to fail with a message that says which rule broke.

A suite that fails on the unmodified store scores nothing, however many mutants
it catches. Randomness that is not seeded is a bug, not a feature: the sequence
has to be reproducible from the test file alone.

## Boundaries

- Write only `tests/test_fencing_stateful.py`. Do not modify `src/`, the existing
  tests, or the configuration defaults.
- Standard library only.
