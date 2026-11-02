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
