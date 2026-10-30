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
