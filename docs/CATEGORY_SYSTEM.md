# Category system

A task category is a registered component, not an enum the engine knows
(implementation plan, section 8.1): adding one is a YAML file, and no change
under `src/akbench/` is required. This page describes the descriptor, what the
nine shipped categories declare, how difficulty is governed, and how the
engine consumes all of it.

## The descriptor

A Category Descriptor lives in `descriptors/categories/`, and the directory
name selects its kind (like every other descriptor, `docs/DESCRIPTOR_SYSTEM.md`).

```yaml
schema_version: "1.0"
id: bug_fix
version: "1.0.0"
title: Bug fix
description: >-
  The repository at the pinned commit contains a controlled defect introduced
  by a versioned mutation patch; the agent restores correct behaviour.

category:
  enabled: true
  difficulties: [easy, medium, hard, expert]
  default_evaluators: [pytest_evaluator]
  task_requirements:
    - repository with a pinned commit
    - versioned mutation patch applied to the base repository
    - mutation verified by the hidden tests before publication
    - hidden tests and evaluator kept outside the agent workspace
```

The body (`src/akbench/descriptors/category.py`, `CategoryBody`) is strict and
has five fields:

| Field | Meaning | Who reads it |
|---|---|---|
| `enabled` | Whether experiments and tasks may use the category | `Dataset._validate_against_registry` refuses a task in a disabled category |
| `difficulties` | The difficulties this category allows, from `easy`, `medium`, `hard`, `expert` | the same validation path, per task |
| `default_evaluators` | The evaluators a task of this category normally uses | advisory: a task names its own evaluator, and both must be registered |
| `task_requirements` | A written contract of what a task of this category must ship | authors and review; see below |
| `notes` | Free text | humans |

`CategoryDescriptor.allows_difficulty(difficulty)` is the one derived question
the model answers, and it answers `false` for a disabled category whatever the
difficulty list says.

## The nine shipped categories

The plan lists `bug_fix` and `new_feature` as the MVP categories and seven
more as the target set; all nine are registered:

| Category | Difficulties it allows | `task_requirements` it declares |
|---|---|---|
| `bug_fix` | easy, medium, hard, expert | a pinned repository; a versioned mutation patch on the base repository; the mutation verified by the hidden tests before publication; hidden tests and evaluator outside the agent workspace |
| `new_feature` | easy, medium, hard, expert | a pinned repository; a functional specification visible to the agent; hidden tests and evaluator outside the agent workspace |
| `refactoring` | easy, medium, hard | a pinned repository; behaviour-preserving acceptance tests |
| `performance` | medium, hard, expert | a pinned repository; a deterministic measurement harness |
| `testing` | easy, medium, hard | a pinned repository; hidden reference tests |
| `security` | medium, hard, expert | a pinned repository; hidden tests proving the vulnerability is closed |
| `debugging` | easy, medium, hard | a pinned repository; a reproducible failure |
| `code_review` | easy, medium, hard | a pinned repository; annotated review targets |
| `architecture` | hard, expert | a pinned repository; architectural acceptance criteria |

All nine are `enabled: true` and all nine name `pytest_evaluator` as a default
evaluator; `new_feature` additionally names `command_evaluator`. The
differences that matter are in the difficulty lists: four categories refuse
`easy` or `expert`, and that refusal is enforced per task by the validator.

## Difficulty

Difficulty is a task metadata field with four values (`docs/TASK_FORMAT.md`).
It changes nothing about the agent, the runtime, the timeout or the evaluator
by itself — plan 8.2 says so explicitly, and the code agrees: an experiment
that wants difficulty to matter has to declare it as a factor or a filter
(`dataset.filters.difficulties`).

What difficulty does have is a gate: a category declares which of the four it
allows, and `akbench dataset validate` fails a task that asks for one the
category does not list (`difficulty ... is not allowed by category ...`).
`architecture` accepting only `hard` and `expert` is that rule doing its work:
a category with a narrow list is stating what its tasks can honestly be, not
filtering the dataset at run time.

## `task_requirements`

`task_requirements` is the written half of a category's contract: the list of
things a task of that kind must ship for its result to mean anything. The
engine enforces some of them elsewhere (a mutation patch exists and is
non-empty, the hidden tests directory exists and is not empty, a `bug_fix`
descriptor without a mutation is refused by the task model itself) and leaves
the rest to review — "mutation verified by the hidden tests before
publication" is a proof `akbench dataset validate --verify-mutations` runs,
not a field a YAML can assert.

Treat the list as the review checklist for a new task: it names the difference
between "a task that is hard" and "a task that cannot be solved, or that
measures nothing".

## Adding a category

Adding a category is one file:

```yaml
# descriptors/categories/documentation_fix.yaml
schema_version: "1.0"
id: documentation_fix
version: "1.0.0"
title: Documentation fix
description: >-
  The documented behaviour and the implemented behaviour disagree; the agent
  restores the documented contract without changing unrelated code.

category:
  enabled: true
  difficulties: [easy, medium, hard]
  default_evaluators: [pytest_evaluator]
  task_requirements:
    - repository with a pinned commit
    - hidden tests over the documented behaviour
    - hidden tests kept outside the agent workspace
```

Then a task directory named after the category id (`datasets/documentation_fix/<task-id>/`),
and nothing else. The registry picks the file up by directory, `akbench
category list` shows it, tasks in it validate against it, and dataset filters
can select it. No engine module names a category: the planner filters tasks by
the category string, the report groups by whatever the tasks carry, and the
validator compares against the registry rather than a list.

That is the test the plan set for this layer (§8.1: "categories may not be a
closed enum"), and it is worth stating how it holds — the category appears in
the engine exactly once, as `DescriptorKind.CATEGORY`, and everywhere else it
is data that came from a file.
