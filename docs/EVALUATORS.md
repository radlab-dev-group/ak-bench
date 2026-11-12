# Evaluator Engine

The evaluator judges the agent's result independently of anything the agent
declares (plan section 16). Two guarantees carry the whole design:

1. **Hidden tests run outside the agent workspace.** They are copied into a
   throwaway copy of the produced workspace, run there, and the copy is removed.
   The agent's workspace is never modified and the hidden tests are never
   visible to it (plan 8.6, 23). This is tested, not assumed.
2. **Raw results are kept.** Every verdict carries the evaluator version, the
   verbatim output and the JUnit XML report, so a pass/fail claim can always be
   re-examined.

## Outcomes

The verdict vocabulary separates what a failed measurement means from what a
failed agent means (plan rule 11):

| Verdict | Meaning |
|---|---|
| `passed` | every hidden test passed |
| `partial` | some passed, some failed |
| `failed` | none passed |
| `regression` | at least one test that passed on the base state now fails |
| `timeout` | the evaluator ran out of time |
| `evaluator_error` | the measurement itself broke (no tests collected, bad invocation, internal error) — never an agent failure |
| `infrastructure_error` | the environment could not run the measurement (e.g. pytest missing) |

Pytest exit codes map to this vocabulary: `0` → pass, `1` → partial/failed/
regression, `5` (no tests collected) and the usage/internal codes →
`evaluator_error`. A missing pytest is `infrastructure_error`, not a zero score.

## Evaluators

All five kinds of plan section 16 are implemented and registered in
`akbench/evaluators/registry.py`. An id outside them is still an explicit
`EvaluatorNotFound` error, never a silent approximation.

- **`pytest_evaluator`** — the primary evaluator and the only one that decides
  a task on its own. Runs the task's hidden tests over a copy of the produced
  workspace.
- **`command_evaluator`** — the generic escape hatch: any command that exits
  `0` on success, run in the same isolation.
- **`diff_evaluator`** — supplementary. Scores the overlap between the
  produced change and a `reference_patch`, line for line, in the base
  coordinates both sides already carry. A diff is evidence about the change,
  never proof of correctness, so the verdict is `partial` when there is
  overlap and `failed` when there is none; it can never return `passed`. It
  reads the workspace read-only instead of copying it, because a diff is a
  relation to the base commit and the evaluation sandbox deliberately drops
  `.git` (see `src/akbench/evaluators/diff.py`).
- **`static_analysis_evaluator`** — supplementary. Runs the analyser the task
  declares (`ruff --output-format=json .` by default) over a copy of the
  workspace and reports its findings as a score: `passed` when the analyser
  found nothing, `partial` when it found something (a reason to look, not proof
  the task is unsolved), `infrastructure_error` when the analyser is not
  installed, and `evaluator_error` when it reports something unreadable.
- **`python_evaluator`** — custom. Runs a task-provided script in a separate
  process against an isolated copy of the workspace; the script reports its
  verdict by writing `evaluator-result.json` into `--out-dir`. Only the plan-16
  vocabulary is accepted, and a script cannot claim `infrastructure_error` —
  that verdict belongs to the evaluator, not to code it cannot verify. The
  script is a host subprocess, not a security boundary (Docker isolation is
  deferred; see `docs/ISOLATION_AND_SECURITY.md`), so a task must ship only a
  script its operator would run by hand.

### Declaring the supplementary inputs

The `diff` and `python` evaluators take their subject from the task, not from
the workspace, so both inputs travel with the task:

```yaml fragment
# a task judged by how close it gets to a reference change
evaluator: diff_evaluator
# and the reference, shipped with the task like a hidden test
mutation:
  patch: mutations/mutation-001.patch
```

In a task descriptor the reference patch and the evaluator script are supplied
as evaluator inputs (`reference_patch`, `script`) when the evaluator is invoked,
either by `akbench evaluate task … --evaluator diff_evaluator` or by code that
calls `EvaluatorEngine.evaluate` with the same keyword arguments. The task's
`evaluator` field always names a registered id; an unknown id is refused by the
registry, which is what keeps a task from being judged by a stand-in.

## Judging a task with several evaluators

A task may declare a list of evaluators; they run in the declared order, each
with its own output directory so their raw reports cannot overwrite one
another, and one verdict is composed from what they reported
(`akbench/evaluators/task_evaluation.py`):

1. **A measurement failure outranks everything.** An `evaluator_error` or
   `infrastructure_error` is reported first: it says nothing about the agent,
   and it is the only thing worth saying.
2. **The hard evaluators decide, in the declared order.** A pass/fail
   evaluator that does not pass ends the composition with its verdict.
3. **A signal can dim a pass, never fail one.** The score-valued kinds
   (`static_analysis_evaluator`, `diff_evaluator`) are advisory: with every
   hard evaluator passed, a finding keeps the run from claiming a clean pass
   (`partial`), but on its own it cannot fail the task.

The composed verdict keeps the primary evaluator's identity, so a historical
row still quotes one evaluator, and `details.evaluators` keeps every part —
which evaluator reported what, and whether it was advisory — so a combined
verdict can always be re-examined. In storage, the composed verdict is the
row with `evaluator_rank = 0`; the parts get ranks 1..n, and readers of a run
quote rank 0. A task judged once writes only the composed row.

```yaml fragment
# a task judged by its tests and by the analyser
evaluator:
  - pytest_evaluator
  - static_analysis_evaluator
evaluator_inputs:
  static_analysis_evaluator:
    command: ruff check --output-format=json .
```

## Using it

```bash
# judge a produced workspace with the task's own evaluator
akbench evaluate task wordcount-001 --workspace data/workspaces/task-workspace --json

# use a supplementary evaluator instead of the one the task names
akbench evaluate task wordcount-001 --workspace DIR --evaluator command_evaluator
```

Exit codes: `0` for a pass, `1` when the agent did not solve the task, and `2`
when the measurement itself broke, so a caller can tell an unsolved task apart
from a broken harness.
