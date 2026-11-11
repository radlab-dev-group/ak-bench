# Datasets, tasks and workspaces (Phase 3)

A **task** is a versioned definition of a benchmark problem. Everything in this
layer is built so that a workspace is *repeatable*: the same task always
produces the same starting state, and a defect is only admitted after tests
prove it exists.

## Task layout

```text
datasets/
  <category>/
    <task-id>/
      task.yaml           # the Task Descriptor (required)
      description.md      # the statement given to the agent
      hidden_tests/       # run by the evaluator, never inside an agent workspace
      public_tests/       # optional, visible tests
      mutations/          # versioned defect patches (required for bug_fix)
        mutation-001.patch
```

The category comes from the descriptor registry, not from a hardcoded enum:
registering a category is a descriptor change (plan 8.1).

## Task Descriptor

```yaml
schema_version: "1.0"
id: wordcount-001
version: "1.0.0"
task:
  category: bug_fix
  difficulty: easy            # easy | medium | hard | expert
  repository:
    source: datasets/_sources/wordcount   # git URL/path or a seed directory
    ref: HEAD                     # branch, tag or commit — resolved per run
  mutation:                     # required for bug_fix
    patch: mutations/mutation-001.patch
    version: "1.0.0"
  evaluator: pytest_evaluator
  hidden_tests: hidden_tests
  public_tests: public_tests
```

`id`, `version` and a stable `uid` (`id@version`) are the task's identity; the
`tasks` table stores one row per uid.

## Repositories and seeds

`RepositoryManager` keeps a bare cache per source under `data/repositories`.

- **git sources** (URL or path to a git repository) are cloned bare and fetched,
  so `ref` is always resolved to a commit hash and recorded on the run.
- **seed directories** (a plain directory, no git metadata) are used for
  fixtures. The cache is built with a fixed identity and fixed commit
  timestamps, so identical content always produces the same commit. Real
  datasets should pin a commit in a real repository; a seed exists so examples
  stay honest and self-contained.

## Workspaces

`WorkspaceManager.prepare` creates a **detached git worktree** of the pinned
commit under `data/workspaces/<workspace-id>`, then applies the mutation to the
*working tree*. Two fingerprints are recorded:

- `tree` — the committed git tree (the pinned state);
- `fingerprint` — the working tree including local changes and untracked files,
  which is the actual content an agent will work on.

A mutation is deliberately **not committed**, so an agent can never read the
defect from `git log`. A workspace is per-run: preparing an already-used id is
refused, and `cleanup` removes both the directory and the worktree
registration.

Hidden tests are never copied into an agent workspace. They are copied in only
for the duration of a verification/evaluation run and deleted afterwards.

## Mutation verification (plan 8.4)

A bug-fix mutation is only accepted if the hidden tests **pass on the base
commit and fail once the mutation is applied**. `MutationVerifier` runs both in
throwaway workspaces and reports:

- `verified` — base passes, mutated fails (the defect is real and detectable);
- `no_mutation` — the task declares no mutation (non bug-fix tasks);
- `base_broken` — the task's own tests do not pass on the pinned base;
- `not_detectable` — the mutation does not break the hidden tests;
- `test_error` — pytest could not run or collect (never counted as a pass).

A pytest exit code of 5 ("no tests collected") is treated as an error, not a
pass.

## Shipped tasks

| task | category | difficulty | fixture | base state vs. hidden tests |
|---|---|---|---|---|
| `wordcount-001` | `bug_fix` | easy | `wordcount` | passes on the base commit, fails once the mutation patch is applied (`verified`) |
| `bookshop-tiers-001` | `bug_fix` | hard | `bookshop` | passes on the base commit, fails once the mutation patch is applied (`verified`) |
| `bookshop-stock-002` | `bug_fix` | expert | `bookshop` | passes on the base commit, fails once the mutation patch is applied (`verified`) |
| `slugify-001` | `new_feature` | easy | `textkit` | fails on the base commit because the feature is missing; passes once the agent implements the specification |
| `notes-search-001` | `new_feature` | hard | `notesapi` | fails on the base commit because the feature is missing; passes once the agent implements the specification |
| `notes-sync-001` | `new_feature` | expert | `notesapi` | fails on the base commit because the feature is missing; passes once the agent implements the specification |
| `cadence-catchup-001` | `new_feature` | expert | `cadence` | fails on the base commit because the feature is missing; passes once the agent implements the specification |
| `cadence-takeover-001` | `bug_fix` | expert | `cadence` | passes on the base commit, fails once the mutation patch is applied (`verified`) |
| `ledgerlite-reconcile-001` | `new_feature` | expert | `ledgerlite` | fails on the base commit because the feature is missing; passes once the agent implements the specification |
| `ledgerlite-rates-001` | `bug_fix` | expert | `ledgerlite` | passes on the base commit, fails once the mutation patch is applied (`verified`) |
| `stockpile-fefo-001` | `new_feature` | expert | `stockpile` | fails on the base commit because the feature is missing; passes once the agent implements the specification |
| `stockpile-writeoff-001` | `bug_fix` | expert | `stockpile` | passes on the base commit, fails once the mutation patch is applied (`verified`) |
| `freight-shop-001` | `new_feature` | expert | `freight` | fails on the base commit because the feature is missing; passes once the agent implements the specification |
| `streamforge-windows-001` | `new_feature` | expert | `streamforge` | missing operators fail public and hidden tests; an external reference implementation passes both |
| `walqueue-recovery-001` | `bug_fix` | expert | `walqueue` | base passes; a multi-module recovery regression fails hidden tests while the seed suite stays green |
| `typeweave-inference-001` | `new_feature` | expert | `typeweave` | missing typechecker fails; an isolated reference passes source, public and hidden tests |
| `depweaver-backtracking-001` | `bug_fix` | expert | `depweaver` | base passes; eight independent regressions fail their own witnesses and the combined mutation preserves the seed suite |
| `atlas-drift-001` | `bug_fix` | expert | `atlas` | base passes; five cooperating regressions in five modules fail their own witnesses and the combined mutation preserves the seed suite |
| `atlas-drift-002` | `bug_fix` | expert | `atlas` | base passes; the one-sided fencing check fails its witnesses (both modes, both directions, the bypassed node) and the seed suite survives |
| `atlas-drift-003` | `bug_fix` | expert | `atlas` | base passes; the flipped tie-break fails its witnesses (the grid, the three-way tie, repair, the digest walk) and the seed suite survives |
| `atlas-drift-004` | `bug_fix` | expert | `atlas` | base passes; the inclusive replay window fails its witnesses (the report counts, the two-image arithmetic) and the seed suite survives |
| `atlas-lineage-001` | `new_feature` | expert | `atlas` | fails on the base commit because the feature is a stub; passes once the agent implements the SPEC section 9 contract, as the isolated reference does |
| `timetable-overlap-001` | `bug_fix` | easy | `timetable` | passes on the base commit, fails once the mutation patch is applied (`verified`) |
| `quiz-streak-001` | `bug_fix` | medium | `quiz` | passes on the base commit, fails once the mutation patch is applied (`verified`) |
| `garden-watering-001` | `bug_fix` | medium | `garden` | passes on the base commit, fails once the mutation patch is applied (`verified`) |
| `playlist-queue-001` | `bug_fix` | hard | `playlist` | passes on the base commit, fails once the mutation patch is applied (`verified`) |
| `cachekit-eviction-001` | `bug_fix` | hard | `cachekit` | passes on the base commit, fails once the mutation patch is applied (`verified`) |
| `timetable-slots-001` | `new_feature` | easy | `timetable` | fails on the base commit because the feature is missing; passes once the agent implements the specification |
| `quiz-ranking-001` | `new_feature` | medium | `quiz` | fails on the base commit because the feature is missing; passes once the agent implements the specification |
| `garden-plan-001` | `new_feature` | medium | `garden` | fails on the base commit because the feature is missing; passes once the agent implements the specification |
| `playlist-mix-001` | `new_feature` | hard | `playlist` | fails on the base commit because the feature is missing; passes once the agent implements the specification |
| `cachekit-ttl-001` | `new_feature` | hard | `cachekit` | fails on the base commit because the feature is missing; passes once the agent implements the specification |
| `csvkit-quoted-field-001` | `debugging` | easy | `csvkit` | fails on the base commit because the defect is present; passes once the agent fixes it |
| `dates-month-boundary-001` | `debugging` | easy | `dates` | fails on the base commit because the defect is present; passes once the agent fixes it |
| `indexer-stale-entry-001` | `debugging` | medium | `indexer` | fails on the base commit because the defect is present; passes once the agent fixes it |
| `pipeline-stage-order-001` | `debugging` | hard | `pipeline` | fails on the base commit because the defect is present; passes once the agent fixes it |
| `retryq-retry-order-001` | `debugging` | medium | `retryq` | fails on the base commit because the defect is present; passes once the agent fixes it |
| `syncer-conflict-001` | `debugging` | hard | `syncer` | fails on the base commit because the defect is present; passes once the agent fixes it |
| `authkit-token-reuse-001` | `security` | expert | `authkit` | fails on the base commit because the vulnerability is present; passes once the agent closes it |
| `authkit-token-timing-001` | `security` | hard | `authkit` | fails on the base commit because the vulnerability is present; passes once the agent closes it |
| `configkit-unsafe-load-001` | `security` | hard | `configkit` | fails on the base commit because the vulnerability is present; passes once the agent closes it |
| `fetcher-open-redirect-001` | `security` | expert | `fetcher` | fails on the base commit because the vulnerability is present; passes once the agent closes it |
| `filebox-path-traversal-001` | `security` | medium | `filebox` | fails on the base commit because the vulnerability is present; passes once the agent closes it |
| `shopdb-sql-injection-001` | `security` | medium | `shopdb` | fails on the base commit because the vulnerability is present; passes once the agent closes it |
| `billing-split-function-001` | `refactoring` | medium | `billing` | fails on the base commit because the target structure is missing; passes once the agent refactors |
| `forms-extract-validator-001` | `refactoring` | easy | `forms` | fails on the base commit because the target structure is missing; passes once the agent refactors |
| `queuekit-deque-migration-001` | `refactoring` | hard | `queuekit` | fails on the base commit because the target structure is missing; passes once the agent refactors |
| `reportgen-split-module-001` | `refactoring` | hard | `reportgen` | fails on the base commit because the target structure is missing; passes once the agent refactors |
| `rules-early-return-001` | `refactoring` | easy | `rules` | fails on the base commit because the target structure is missing; passes once the agent refactors |
| `session-explicit-state-001` | `refactoring` | medium | `session` | fails on the base commit because the target structure is missing; passes once the agent refactors |
| `cachekit-lru-001` | `testing` | easy | `cachekit` | the agent's tests must pass on the correct code and fail on a mutated variant |
| `garden-watering-tests-001` | `testing` | hard | `garden` | the agent's tests must pass on the correct code and fail on a mutated variant |
| `playlist-queue-tests-001` | `testing` | hard | `playlist` | the agent's tests must pass on the correct code and fail on a mutated variant |
| `quiz-streak-tests-001` | `testing` | medium | `quiz` | the agent's tests must pass on the correct code and fail on a mutated variant |
| `timetable-overlap-tests-001` | `testing` | medium | `timetable` | the agent's tests must pass on the correct code and fail on a mutated variant |
| `wordcount-top-words-001` | `testing` | easy | `wordcount` | the agent's tests must pass on the correct code and fail on a mutated variant |
| `review-api-break-001` | `code_review` | hard | `apikit` | REVIEW.md must name the seeded issues in the PR |
| `review-leak-001` | `code_review` | easy | `leakkit` | REVIEW.md must name the seeded issues in the PR |
| `review-pr-large-001` | `code_review` | hard | `largekit` | REVIEW.md must name the seeded issues in the PR |
| `review-pr-multi-001` | `code_review` | medium | `multikit` | REVIEW.md must name the seeded issues in the PR |
| `review-pr-small-001` | `code_review` | easy | `reviewkit` | REVIEW.md must name the seeded issues in the PR |
| `review-race-001` | `code_review` | medium | `racekit` | REVIEW.md must name the seeded issues in the PR |
| `config-cache-001` | `performance` | hard | `configkit` | fails on the base commit because the implementation does too much work (counted operations); passes once optimized |
| `dedup-linear-001` | `performance` | medium | `dedupkit` | fails on the base commit because the implementation does too much work (counted operations); passes once optimized |
| `fib-memo-001` | `performance` | hard | `fibkit` | fails on the base commit because the implementation does too much work (counted operations); passes once optimized |
| `index-lookup-001` | `performance` | medium | `indexkit` | fails on the base commit because the implementation does too much work (counted operations); passes once optimized |
| `inverted-index-001` | `performance` | expert | `searchkit` | fails on the base commit because the implementation does too much work (counted operations); passes once optimized |
| `sorted-search-001` | `performance` | medium | `sortedkit` | fails on the base commit because the implementation does too much work (counted operations); passes once optimized |
| `eventbus-decoupling-001` | `architecture` | expert | `eventbus` | fails on the base commit because the target structure is missing; passes once the agent restructures |
| `inventory-repository-001` | `architecture` | hard | `inventory` | fails on the base commit because the target structure is missing; passes once the agent restructures |
| `plugcore-registry-001` | `architecture` | expert | `plugcore` | fails on the base commit because the target structure is missing; passes once the agent restructures |
| `shopcore-layered-001` | `architecture` | hard | `shopcore` | fails on the base commit because the target structure is missing; passes once the agent restructures |

`slugify-001` declares no mutation, so `--verify-mutations` reports
`no_mutation` for it. Its honesty check lives in
`tests/integration/test_workspaces.py`: the hidden tests must fail on the base
state and pass against a reference implementation.

### The easy/medium/hard family

Ten tasks over five new standard-library fixtures (`timetable`, `quiz`,
`garden`, `playlist`, `cachekit`), one `bug_fix` and one `new_feature` per
fixture, fill the difficulty levels the earlier dataset barely touched
(two `easy`, no `medium`, two `hard` before them). Each fixture is a
complete, working package with one finished module carrying the bug-fix
defect and one declared stub carrying the new-feature specification, so
both tasks share the same seed exactly as the `bookshop` and `notesapi`
pairs do. Difficulty follows the shape of the work: `easy` is a single
function with a single boundary (`timetable-overlap-001`,
`timetable-slots-001`), `medium` adds a second interacting rule (a streak
reset, a rain postponement, a shared rank, a capacity-limited plan), and
`hard` keeps the defect small but hides it behind a pipeline or a stateful
sequence (disc-before-track ordering, a read that must refresh recency, a
greedy mix with a tolerance, a TTL cache whose `put` reclaims expired
entries before evicting a live one). The integrity suite is
`tests/integration/test_arena_dataset_tasks.py`: it proves every new
mutation `verified` with the seed suite green in both states, and every
new feature missing on the seed (`NotImplementedError`) and complete under
its isolated reference, which never enters a seed or an agent workspace.

```bash
python -m pytest tests/integration/test_arena_dataset_tasks.py
```

### What makes the harder tasks hard

The two `bookshop` tasks are one working Flask service with two defects. Each
defect leaves the fixture's own suite green, so an agent cannot watch a red
test: `bookshop-tiers-001` is wrong only at a subtotal that sits exactly on a
tier threshold, and `bookshop-stock-002` is a missing release that shows up as
an inventory count nobody asserts on. Finding either means reading the rules
and following an invariant.

The two `notesapi` tasks are specifications rather than puzzles: `search_notes`
and `merge` are declared, their contract is written in the module docstring,
and the body raises `NotImplementedError`. `notes-sync-001` is the harder of
the pair because its contract has to be complete — every branch says who wins
and which list the id lands in, including the branches a careless spec would
leave out (an older client write, a conflict, an id only the server has).

The two `cadence` tasks run on a working, stdlib-only job scheduler: cron
schedules resolved in a time zone, a dependency graph, a write-ahead log, and
leases with epochs. `cadence-takeover-001` is the harder of the bug-fix pair:
the defect is a missing epoch check in `LeaseBook.takeover`, so a worker that
was cut off and comes back can steal the resource from the holder that has it
now — and every count the repository suite looks at stays intact, because the
suite only ever takes a resource back by the epoch it still carries.
`cadence-catchup-001` is the catch-up planner: declared and specified to the
occurrence in the module docstring (the window, the two dependencies and their
skip propagation, the per-task cap, the ordering) and not yet written; the
plan must come back in an order the scheduler could execute top-down.

The two `ledgerlite` tasks run on a complete, stdlib-only double-entry ledger:
a chart of accounts with normal sides, an append-only journal that refuses
unbalanced entries, an FX rate book that converts as of a moment, a half-open
period close, and a bank reconciliation. `ledgerlite-rates-001` is the harder
of the pair: once a currency's rate is revised, `rate_for` answers with the
first published rate at or before the moment instead of the last, so every
conversion is silently valued at the superseded rate — and the repository suite
only ever publishes one rate per currency, for which first and last are the
same. `ledgerlite-reconcile-001` is the reconciliation itself: declared and
specified to the claim in the module docstring (the exact-amount rule, the
window and how days are counted, the two passes and their ordering, what stays
open) and not yet written.

The two `stockpile` tasks run on an inventory engine: lots with receipt and
expiry dates, reservations that are not taking, commits that are, transfers
that carry the expiry with them, and a movement ledger. `stockpile-fefo-001`
is the first-expired-first-out allocation: declared and specified to the unit
in the module docstring (eligibility, what an earlier plan does to a lot, the
order and its two tie-breaks, how much each lot gives, and why a partial plan
is never returned) and not yet written. `stockpile-writeoff-001` is the
harder of the pair: a write-off zeroes the reserved quantity of an expired lot
along with its free quantity, so an order already holding stock on the lot is
left with nothing to commit — and the repository suite only ever writes off an
expired lot that carries no reservation.

The `freight-shop-001` task runs on a freight rate-shopping engine: a zone
table that reads postal codes by longest prefix, a billable-weight rule that
rounds exactly once and only at the end, rate cards that refuse what they will
not carry, and surcharges with their own base, group and ordering rules.
`shop` is declared and specified to the cent in the module docstring — who
gets asked and who is refused with what reason, per-carrier billable weight,
the surcharge pass in declaration order with its groups and its tie between
equal amounts, the two tie-breaks of the cheapest quote, and why an empty run
is an error — and not yet written.

### Durable-state expert tasks

`streamforge-windows-001` requires coordinated implementation in three modules,
not a single function: fixed and non-divisible sliding windows, transitively
merged sessions, ordered retract/upsert output, partition watermarks and
idleness, deduplication, strict finalization and complete checkpoint recovery.
Late input can merge emitted sessions and reopen the resulting session, so
window arithmetic alone is insufficient. Negative event times, independent
keys, reordered declarations, atomic error handling and fresh-process restore
are specified. Hidden tests compare generated traces against an independent
batch implementation that groups raw events rather than using production
operators. Operator-level tests also check snapshot consistency and ownership.

`walqueue-recovery-001` provides a complete transaction queue with segmented,
checksummed WAL frames, atomic snapshot publication, permanent request keys,
retry/dead-letter states and generation-fenced leases. Its mutation introduces
a faulty recovery fast path across snapshot projection, publication selection,
replay boundaries and torn-tail repair. A successful fix must preserve the
entire protocol: completed/dead tombstones, active leases, generations, original
idempotency identities, and every complete transaction before a torn tail.
Hidden tests cover every append/compaction crash phase, second restarts, suffix
replay, orphan snapshots, corruption and independent generated queue traces.
Crashes are deterministic exceptions at explicit phases; tests use no sleeps,
real services or assumptions about worker timing.

Both tasks allow 7200 seconds for an agent and use the existing `expert`
difficulty and `pytest_evaluator`. This timeout is an upper bound, not a claim
about required runtime or a guarantee that any particular model will fail.
Their infrastructure and seeds depend only on the standard library; pytest
is supplied by AK-Bench. The integration proof is
`tests/integration/test_durable_dataset_tasks.py`. The Streamforge reference
implementation lives under `tests/fixtures/streamforge_solution`, outside the
seed, so agents never receive it in their prepared workspace.

Run the focused benchmark integrity checks with:

```bash
python -m pytest tests/integration/test_durable_dataset_tasks.py
akbench dataset validate --check-repositories --verify-mutations
```

The integrity checks prove missing-feature failures, reference-solution passes,
base/mutated bug detection, and seed-suite compatibility. Hidden tests and
reference code must remain outside the source projects. Runtime APIs and the
source README contracts are English, as are the other shipped tasks.

### Compiler and dependency-solver expert tasks

`typeweave-inference-001` supplies approximately 4,000 lines of production Python
across a working compiler front end, interpreter, independent bytecode VM, AST
and artifact codecs, source packages, dependency graphs, incremental compilation,
module linking and versioned editor services. The missing feature occupies five
modules: substitution/unification, Hindley–Milner inference, nominal datatype
elaboration, recursive pattern matrices and portable module interfaces. A correct
implementation must combine normalized environment generalization, monomorphic
recursive SCCs, a conservative value restriction, an occurs-check, deferred typed
coverage and closed alpha-normalized exports. Hidden tests include transitive
nominal types, opaque constructor families, independently loaded schemes, deep
patterns, source provenance, generated programs and their ill-typed neighbors.
They exercise both runtimes, typed editor inspections and interface-sensitive
artifact reuse. The reference lives in `tests/fixtures/typeweave_solution`, never
inside the seed or the prepared agent workspace.

`depweaver-backtracking-001` supplies approximately 4,300 lines of production
Python: semantic versions, parsed environment markers, metadata indexes,
fixed-point feature propagation, a trailed solver, contextual clause learning,
backjumping, domain caching, target-bound lockfiles and partial updates. Project
tooling includes TOML profiles, multi-target bundles, replayable sessions,
transactional workspace lock publication, independent validation, graph and
conflict explanations, offline advisories, installation plans, inventories,
wheel/RECORD inspection and content-addressed artifact storage. Eight injected
regressions affect rollback, re-expansion after feature activation, feature union,
owner-relative markers, clause context, request scoping, cache context and pins
outside the update set. Tests check each defect independently, compare generated
small repositories against an exhaustive oracle, and include larger domains
with a decision budget. The oracle is only a test tool; production search must
retain working caching, learning and nonchronological conflict return.

Production line counts exclude tests, documentation, patches and external
reference code. Both tasks use `expert`, `pytest_evaluator` and a 10,800-second
agent timeout. The timeout permits sustained work; difficulty is established by
the specified interactions and regression proofs, not by guaranteed failure of
a particular model. Both projects require only Python 3.12's standard library
plus the benchmark's pytest runner.

The integrity suite is `tests/integration/test_senior_dataset_tasks.py`. It proves
the compiler feature is missing on the seed and complete under its isolated
reference, verifies the resolver's combined base/mutated behavior, confirms the
source suite stays green after mutation, and applies each of eight separate
regression patches against its named hidden witness. These checks complement
the earlier durable-state tasks and dataset CLI discovery/validation checks.

```bash
python -m pytest tests/integration/test_senior_dataset_tasks.py
```

### The atlas sharded-store family

Five tasks over one fixture: `datasets/_sources/atlas`, a standard-library-only
sharded, replicated, fenced key-value store of roughly five thousand lines of
production code, twenty-four modules, a 41-test suite, a normative
`SPEC.md` and a corpus of 176 incident notes. The store is complete and its
suite is green; the tasks are defects and one missing feature that the suite
does not see.

The family is shaped for the memory experiment, and that is why it exists in
this shape:

* `atlas-drift-001` is the **learning task**: five cooperating regressions,
  one per module (placement, fencing, torn-tail repair, tie-break, replay
  boundary). A session that works it is long enough that the knowledge
  plugin's recipes, dead-end records, playbooks and the compaction archive
  all fire; each of the five fixes is a principle — the invariant it
  restores — and the wrong modules the session rules out are recorded as
  dead-ends.
* `atlas-drift-002`/`-003`/`-004` are the **twins**: one regression each, in
  a different module than the learning task's patch touches, and written so
  that a recipe from the learning task transfers as a principle, not as a
  diff. Each twin's `description.md` points at the rule by the symptom
  (the notes in `docs/incidents/` do the same), and each twin plants its own
  two incident notes, one of which is the plausible-but-wrong argument —
  the reverted one-sided check, the ascending tie-break that "sorts first",
  the snapshot's own inclusive boundary — that makes a wrong fix pass
  review.
* `atlas-lineage-001` is the **new-feature task** of the family: a declared
  stub (`src/atlas/lineage.py`, every method `NotImplementedError`)
  implemented against the normative contract in `SPEC.md` section 9, with
  the reasoning in `docs/lineage.md`. The reference implementation lives in
  `tests/fixtures/atlas_lineage_solution` and never in the seed or the
  prepared workspace.

What makes the family hard for a model without memory is the split between
the *rule* and the *line*. The rule is in the documentation and in the
incidents, but the incidents are two hundred notes long and the ones that
matter are written about the symptom, so they are not found by searching for
the module name. The line is in one module, and the module is not where the
symptom points: the tie-break lives in repair, the window in storage, the
check in fencing, and a third note in each twin's corpus reads, at a glance,
like it is about the defect and is about a different one. The repository
suite is green on the base and green after the mutation, so the only red
signal is the hidden scenario, and the hidden scenario is written the way
the rule is written — as arithmetic and as reports, not as a diff of the
defective line.

The family's integrity checks live in
`tests/integration/test_atlas_family_tasks.py`: each twin verifies
(`verified`), the seed suite survives each mutation, the learning task's
five parts each break their own witness, and the lineage stub fails while
the isolated reference passes.

```bash
python -m pytest tests/integration/test_atlas_family_tasks.py
```

### Fixtures and their dependencies

A task runs with the interpreter that runs AK-Bench, so a third-party package a
fixture imports is a dataset requirement. `bookshop` and `notesapi` need Flask,
declared as the `datasets` extra:

```bash
uv pip install -e ".[dev,datasets]"
```

A missing dependency is reported by the evaluator as an infrastructure error,
never as an agent failure.

## CLI

```bash
akbench dataset list [--category C] [--json]
akbench dataset validate [--check-repositories] [--verify-mutations] [--json]
akbench dataset show REFERENCE [--json]
akbench dataset prepare REFERENCE [--workspace-id ID] [--no-mutation] [--json]
```

`validate` cross-checks every task against the descriptor registries (category
registered and enabled, difficulty allowed, evaluator registered, hidden tests
present, directory matches the id) and, with `--verify-mutations`, proves each
mutation. It exits 1 if any task fails.

## What is deliberately not here yet

The evaluator *engine* that runs hidden tests against an agent's produced
workspace (plan 16) lands in Phase 6; the `evaluator` field in a task names the
descriptor that will do it. Knowledge/Replay isolation (plan 17) and the
reproducibility manifest (plan 14) build on the fingerprints recorded here.
