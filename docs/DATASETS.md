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
| `atlas-quorum-001` | `bug_fix` | expert | `atlas` | base passes; four regressions in two antagonistic pairs fail their own witnesses, the seed suite survives |
| `atlas-quorum-002` | `bug_fix` | expert | `atlas` | base passes; the read branch of the same quorum rule fails the hidden scenario, the suite stays green |
| `atlas-quorum-003` | `bug_fix` | expert | `atlas` | base passes; the same invariant broken in `rebalance`, a module the learning patch never touches |
| `atlas-quorum-004` | `bug_fix` | expert | `atlas` | base passes; a learning-task failure message reproduced from another cause, so the remembered recipe is a trap |
| `atlas-schema-001` | `new_feature` | expert | `atlas` | the row half of SPEC section 10 is a stub and its goldens unverified; the isolated reference and the documented generate/lock/verify procedure complete both |
| `atlas-schema-002` | `new_feature` | expert | `atlas` | index projection is declared and missing; another surface of the schema, the same procedure and the same tools |
| `depweaver-lockfile-001` | `new_feature` | expert | `depweaver` | canonical form, lock digest and proofs of solution are declared stubs; the isolated reference reproduces the documented digests offline |
| `tidewater-election-001` | `bug_fix` | expert | `tidewater` | base passes; five election regressions in two antagonistic pairs and a single, all ending in one `election_safety` line, fail their own witnesses and the combined mutation preserves the seed suite |
| `tidewater-election-002` | `bug_fix` | expert | `tidewater` | base passes; the same majority decision broken in `membership`, the module the learning patch never opens |
| `tidewater-election-003` | `bug_fix` | expert | `tidewater` | base passes; the learning task's two-leaders line from legal ballots counted against the wrong machine, so the remembered rule is a trap |
| `tidewater-snapshot-001` | `new_feature` | expert | `tidewater` | the node half of SPEC section 6 is declared; the isolated reference takes the record, keeps the boundary term, restarts from it, and lands the corpus entry through the documented tools |
| `tidewater-snapshot-002` | `new_feature` | expert | `tidewater` | the transfer half of SPEC section 6 is declared; the reference streams and installs the snapshot, survives a crash mid-transfer, and lands its own corpus entry the same way |
| `walqueue-compaction-002` | `bug_fix` | expert | `walqueue` | base passes; four cooperating compaction regressions fail their own witnesses and the combined mutation preserves the seed suite |

`slugify-001` declares no mutation, so `--verify-mutations` reports
`no_mutation` for it. Its honesty check lives in
`tests/integration/test_workspaces.py`: the hidden tests must fail on the base
state and pass against a reference implementation.

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

### The memory suite

Thirteen tasks over four seeds (`atlas`, `tidewater`, `depweaver`, `walqueue`),
written for one question: does a model that remembers — recipes, dead ends,
playbooks and a documentation map carried over from a previous session by the
`agentic_knowledge` plugin — do something a model that does not cannot? The
design rules are in `.plans/memory-suite-plan.md`; the experiment that measures
them is `configs/experiments/knowledge-replay-memory-suite.yaml`
(`docs/KNOWLEDGE_REPLAY.md`). Every task in the suite obeys the same five rules,
and each rule exists to make one plugin mechanism matter:

* **antagonistic defect pairs** — the obvious fix of one regression re-raises
  another with the *same* exception type and message, and the reverse; a
  memoryless agent oscillates, the plugin records the recurrence as a dead end
  and counts the loop, and the rule that resolves both halves is written down
  once. Only the documentation settles a pair.
* **the truth is in the documentation, and there is a lot of it** — ADRs,
  incident notes and runbooks, with the decisive rule stated by *symptom* in
  exactly one record, incident notes that name the wrong module on purpose, and
  a README that is deliberately a little stale where the rule lives;
  `CONTRIBUTING.md` gives the hierarchy of truth. This is what the
  documentation map and its `doc_type`-filtered hits have to find.
* **procedural debt** — the new features are only finished once a repository
  tool has been run with the right flags (regenerate, lock, verify the goldens
  or the trace digests) and its artefacts are left in the tree; skipping the
  step fails with a stable error the public tests never show. A session that
  did it once leaves a playbook its twin can spend.
* **noise that forces compaction** — the simulations print long traces, and a
  hash, epoch, offset or segment name found mid-session is asserted at the end,
  which is what the session archive survives for.
* **twins that share one failure signature** — a twin whose recipe fits as it
  is, a twin where only the principle transfers, and a twin where the same
  signature has a different cause and the remembered recipe is the trap.

`atlas-quorum-001` is the second learning task of the atlas seed: four
regressions in two pairs. Pair A counts the acknowledgment of a retiring
replica towards the write quorum and leaves that same replica out of the
convergence pass, so tightening one loosens the other with the same
`ConvergenceError`; pair B writes a repaired value one generation ahead of
itself and lets the lease book follow a non-forward generation. The fix of
either half, applied naively, reproduces the other half's message, and the
rule that settles each pair is `ADR-0002` (a retiring replica holds but does
not vote) and `ADR-0003` (a version is minted once), one ADR per pair.
`atlas-quorum-002` is the exact-signature twin — the read branch of the very
same quorum rule, where the recipe fits as it stands. `atlas-quorum-003` is the
related twin: the invariant broken in `rebalance.py`, which the learning patch
never opens, so what has to transfer is the rule and not the diff.
`atlas-quorum-004` is the negative twin: the learning task's
`ConvergenceError: shard N did not converge for epoch N` again, from a
different cause in the vector clock, with nothing being retired; the incident
note that explains the old cause is evidence, not a rule, and the recipe that
applies it makes the hidden tests worse.

`atlas-schema-001` and `atlas-schema-002` are the procedure pair. The first
implements the row half of `SPEC.md` section 10 — upgrade on read, dual-write
for a pinned reader, downgrade, registration — and must run the repository's
schema procedure, `tools/gen_tables.py --lock` and `tools/verify_goldens.py`
against `schema/MANIFEST`, leaving the generated tables and the goldens in the
tree. The second implements index projection and declares a fourth index, and
has to run the same procedure for a different surface. The guide that states
the procedure, `docs/schema-evolution.md`, is not mentioned by the README, and
the goldens fail with a `GoldenMismatch` that names the record, not the
missing step.

`depweaver-lockfile-001` is a learning task replayed on itself: the canonical
serialisation of a resolution, its digest, proofs of solution that verify
without the solver, and proof-driven invalidation of cached resolutions. One
`ProofInvalid` sits behind three different causes, so two of the three obvious
fixes are dead ends the plugin records by name; `tools/relock.py --canonical
--prove` and `tools/verify_lock.py` have to reproduce the documented digests.

`tidewater-election-001` is the learning task of the new `tidewater` seed, a
deterministic Raft-lite simulator: five regressions in two antagonistic pairs
and a single — a candidate that answers a rival in its own term, a candidate
that counts an answer from a closed term, a granted vote that replies before it
is durable, a `sync` that no longer makes the recorded vote durable, and an
election that inherits the tally of the one that failed. All five end in the
same `election_safety` line — `term N has two leaders: A and B` — which is what
makes a pair a pair: the obvious fix of one half re-raises the other. The
resolving rule is `ADR-0013` (one ballot per term) and the incident note that
names the wrong module. `tidewater-election-002` is the related twin: the same
decision — a majority of the configuration — broken in `membership.py`, which
the learning patch never opens. `tidewater-election-003` is the negative twin:
the two-leaders line from *legal* ballots counted against the machine an answer
arrived through rather than the machine it names; the learning recipe applies
there and makes the hidden tests worse.

`tidewater-snapshot-001` and `tidewater-snapshot-002` are the new-feature pair
of the seed: the node half of `SPEC.md` section 6 (take the record at
`last_applied`, keep the boundary term, restart from the snapshot, make a
snapshot event committed-visible) and then its other half — the stream and the
install (6.4, 6.5, the crash mid-transfer), which is the related transfer of the
*procedure*, not of the code: each task lands its own corpus entry through
`tools/gen_schedules.py --lock` and `tools/reference_traces.py`, and the
reference of the earlier task does not finish the later one.

`walqueue-compaction-002` is the walqueue member of the suite: four cooperating
regressions in the compaction path of the durable queue — a segment name
reissued after it was deleted, a write after a compaction landing in the
compacted segment, a torn tail accepted from a non-newest segment, and an
interrupted compaction pruning work it had not published — two of them two
halves of one rule whose obvious fixes undo each other, resolved by the
documented rule stated by symptom.

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
