# Run Orchestrator

The orchestrator drives one run through its lifecycle using only the generic
contracts: the agent registry and adapter, the runtime registry and execution
mode, the workspace manager and the evaluator engine (plan section 15). There
is no agent-specific code in it — a new agent is a descriptor plus an adapter,
never a change to the runner.

## Lifecycle

```text
PENDING -> PREPARING -> VALIDATING -> CONFIGURING_RUNTIME -> CREATING_WORKSPACE
       -> STARTING_AGENT -> EXECUTING -> COLLECTING -> EVALUATING -> FINALIZING
       -> COMPLETED
```

Transitions are validated: a step cannot be skipped and a terminal state cannot
be left. The plan's forward chain is recorded even when a step is a no-op (in
`direct` mode the runtime step is logged as "no runtime"), so the history of a
run does not depend on incidental choices.

Terminal failure states separate *why* a run did not complete, so an
infrastructure error is never read as an agent failure (plan rule 11):

| State | Meaning |
|---|---|
| `completed` | the run reached the evaluator; `ok` says whether the task was solved |
| `failed` | the agent reported a failure |
| `timeout` | the agent ran out of time |
| `cancelled` | the run was cancelled |
| `infrastructure_error` | the environment could not run the agent |
| `invalid_configuration` | the configuration or environment was rejected before the agent started |
| `evaluation_error` | the measurement itself broke |

## Retries

An agent failure is **never retried** — retrying would measure the retry
instead of the agent. Infrastructure failures are retried only when the caller
sets `infrastructure_retries` (it defaults to `0`), and every retry is recorded
in the run's transition log, so the history always shows how many attempts a
run took.

## Isolation and artifacts

Each run gets its own workspace (plan section 14): a detached git worktree of
the pinned commit, the task's mutation applied on top when declared, and a
private agent home. The workspace's base commit and fingerprint are recorded in
the transition log at creation, so a workspace is repeatable and auditable.

Every run writes `run_record.json` next to the agent's own artifacts. It
contains the full transition log, the workspace fingerprints, the agent
observations and the evaluation verdict (including the verbatim evaluator
report). That record is the audit trail of one run and the input to storage and
reports in later phases.

## Using it

```bash
# one orchestrated run: prepare, execute, evaluate, record
akbench run single wordcount-001 --agent codex --json

# the same, without the task's mutation (the pristine repository)
akbench run single wordcount-001 --agent codex --no-mutation

# an explicit retry budget for infrastructure failures only
akbench run single wordcount-001 --agent codex --infrastructure-retries 2
```

Exit code: `0` when the run completed and the task was solved, `1` otherwise.
The JSON payload carries the terminal state, the verdict, the workspace and the
path of the run record.

Programmatic use takes the same shape the CLI uses: build the registries,
construct an `OrchestrationConfig` and call `RunOrchestrator.run`. The returned
`RunOutcome` carries the terminal state plus the complete run record.
