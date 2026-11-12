# Task format

A task is a versioned definition of a benchmark problem, not a directory
listing (plan section 8.3): a stable id, a pinned repository state, a category,
a difficulty, and the evaluation that decides it. This page is the field-by-field
reference for `task.yaml` as read by `src/akbench/datasets/task.py`, the layout
a task directory must have, and the two rules that keep the defect honest.

## The directory

```text
datasets/
  <category>/
    <task-id>/
      task.yaml           # the Task Descriptor (required)
      description.md      # the statement given to the agent
      public_tests/       # optional, visible to the agent
      hidden_tests/       # run by the evaluator only, never in an agent workspace
      mutations/          # versioned defect (required for bug_fix)
        mutation-001.patch
        parts/            # optional: the patch split into pieces
        parts.json        # optional: what names the pieces (see below)
```

The category directory is part of the layout, and the category itself comes
from the descriptor registry, not from an enum (`docs/CATEGORY_SYSTEM.md`).
The dataset root is `datasets/`, loaded by `Dataset.load`
(`src/akbench/datasets/dataset.py`); every task directory is a directory that
contains a `task.yaml`, and the dataset refuses to load twice under one uid.

## `task.yaml`, field by field

The document has the descriptor header — `schema_version`, `id`, `version`,
and optionally `created_at`, `title`, `description`, `authors` — and a `task:`
body. The body is strict: an unknown key is a load error, so a field nobody
reads cannot quietly sit in a task.

### `task.category`

The category's descriptor id (required). It selects the category's rules, such
as "a bug fix must declare a mutation" (see below). The value must be a
registered, enabled category: `akbench dataset validate` checks it against the
registry, and the category descriptor decides which difficulties it allows.

### `task.difficulty`

One of `easy`, `medium`, `hard`, `expert` (required). Difficulty is metadata:
it does not change any agent parameter unless an experiment says so (plan
8.2). A difficulty the task's category does not allow is a validation failure.

### `task.repository`

Where the task's code comes from and which state is pinned (required):

| Field | Meaning |
|---|---|
| `source` | A git URL, a path to a git repository, or a local seed directory (`datasets/_sources/<name>`). Relative local sources resolve against the project root |
| `ref` | The base commit, or a branch/tag that resolves to one. A branch name alone is not reproducible, so the resolved commit hash is recorded per run |
| `subdir` | Optional. The working directory inside the repository when the task is not the whole repo |
| `notes` | Optional free text |

`RepositoryManager` keeps a bare cache per source under `data/repositories`:
git sources are cloned and fetched so `ref` always resolves to a commit; seed
directories are cached with a fixed identity and fixed commit timestamps so
identical content always produces the same commit.

### `task.mutation`

The controlled, versioned defect applied on top of the base commit (plan 8.4).
Optional in the body, **required for `bug_fix`** — a task that declares the
category without a patch is a descriptor error, because a bug fix with no
planted defect is not one:

| Field | Meaning |
|---|---|
| `patch` | The patch file, relative to the task directory |
| `version` | The mutation's own version |
| `verification` | How the defect was proven; the convention is `hidden_tests` — the hidden tests must fail once the patch is applied |
| `notes` | Optional free text |

The patch is applied by the workspace manager at prepare time, left
**uncommitted** on purpose: the defect must not appear in the git history of
the workspace the agent works in. A `new_feature` task declares no mutation —
its base state is expected to fail the hidden tests by design, the opposite
of the bug-fix convention.

#### Multi-part mutations: `parts.json`

A defect with several independent pieces ships them separately:

```text
mutations/
  mutation-001.patch    # still the patch the descriptor names
  parts/
    01-first-piece.patch
    02-second-piece.patch
  parts.json
```

`parts.json` is a JSON list of `{"patch": <path relative to mutations/>,
"witness": <test id>}`. The witness names the hidden test that fails for that
piece, which is what the integration suites use to prove each piece exists.
The integrity guard (`tests/unit/test_dataset_integrity.py`) refuses a
`parts.json` whose named pieces are missing from `parts/` — the failure mode
this guard was written for is a patch directory that git stopped tracking
while the index still named it.

### `task.evaluator`

The evaluator that judges the task (required): one registered evaluator id,
or a list of them when the task is judged by more than one measurement. Every
id must be a registered evaluator descriptor and one this installation
implements — the planner refuses a task that would be judged by a stand-in
(`docs/EVALUATORS.md`). The first entry is the primary: what a
single-valued reader quotes. The shipped convention is `pytest_evaluator`;
the supplementary evaluators take their subject from the task, not from the
workspace.

### `task.evaluator_inputs`

Per-evaluator inputs, keyed by evaluator id: the `command` a command or
static-analysis evaluator runs, the `script` a Python evaluator runs, the
`reference_patch` a diff evaluator measures against. Only evaluators the task
declares may be named here — an input for an evaluator nobody calls would sit
unread, and the dataset validator fails the task for it. Keeping the inputs
with the task is what makes a verdict reproducible from the task alone.

### `task.hidden_tests` and `task.public_tests`

Directories inside the task, relative to the task directory. `hidden_tests`
defaults to `hidden_tests`; `public_tests` is optional. The split is a
security boundary, not a convenience: the hidden tests never enter an agent
workspace and are copied into the evaluation sandbox only for the duration of
one evaluation (`docs/ISOLATION_AND_SECURITY.md`).

### `task.setup`, `task.timeout_seconds`, `task.constraints`, `task.notes`

- `setup` — a list of shell commands the task may declare to run in the
  workspace before the agent starts (default: none). The field is part of the
  descriptor and is validated with it; today nothing executes it — no shipped
  task declares one and the orchestrator's prepare step does not run it — so
  it is declared capacity, and a task that needed it would need the runner
  change that goes with it.
- `timeout_seconds` — the per-run budget the task declares (optional). A task
  timeout above the experiment's `execution_policy.timeout_seconds` is a
  planning error (`task_timeout_exceeds_experiment`): the experiment's bound
  is what the run is allowed.
- `constraints` — a list of stated limits for the agent (do not change the
  public API, do not add dependencies, …). They are part of the task text.
- `notes` — optional free text.

## The task's identity

`id` and `version` are the identity; the stable cross-reference used in the
database, the history and the run records is the uid `id@version`
(`TaskDescriptor.uid`). A task's content is digested the same way a
descriptor's is — the digest of the descriptor plus the files the evaluation
depends on — and that digest is what a plan pins, so a task edited after a
run is a different task, not a reinterpretation.

## The two rules that keep the defect honest

1. **The mutation is verified before the task is published.** For a bug fix
   the hidden tests must fail with the patch applied and pass without it.
   `akbench dataset validate --verify-mutations` runs that proof; a task whose
   defect the tests do not see is broken, not "harder".
2. **The hidden tests stay outside the agent.** The descriptor references them
   by path and never embeds them; the workspace manager copies the repository,
   not the task directory, and the evaluator is the only component that reads
   the hidden tests.

## What a task is not

It is not a script, a fixture server or a test harness. It is a versioned
claim — "this repository at this commit, with this defect, judged by this
evaluator" — and everything the claim depends on (the patch, the tests, the
evaluator's inputs) travels with it under the task directory.
