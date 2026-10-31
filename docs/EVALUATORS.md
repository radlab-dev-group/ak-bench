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

- **`pytest_evaluator`** — the primary evaluator. Runs the task's hidden tests
  over a copy of the produced workspace.
- **`command_evaluator`** — the generic escape hatch: any command that exits
  `0` on success, run in the same isolation.

The `diff`, `static_analysis` and `python` kinds have descriptors but no
implementation in this installation; asking for one is an explicit
`EvaluatorNotFound` error, never a silent approximation. Adding an evaluator
means implementing the contract and registering it in
`akbench/evaluators/registry.py` — the engine, the tasks and the CLI do not
change.

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
