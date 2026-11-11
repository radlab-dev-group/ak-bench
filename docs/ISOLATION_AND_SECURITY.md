# Isolation and security

What AK-Bench keeps apart, how it does it, and what it does not claim. The
threat model is a research benchmark run by its operator on a machine the
operator controls, against agents that execute real code in workspaces cut
from real repositories (implementation plan, sections 14 and 23). This page is
written to be read before trusting a result — and before trusting a machine to
an agent.

## The threat model

Three things are worth protecting during a run:

1. **The answer key.** A task's hidden tests and its planted defect. If an
   agent can read them, the run measures reading, not solving.
2. **The measurement.** The dataset, the evaluators, the experiment definition
   and the artifacts of other runs. An agent that can write there can change
   what its own result means, and what the next run means.
3. **The machine and its secrets.** The operator's files, credentials and the
   history database. Agent output routinely contains secrets it read; the risk
   is what gets *recorded* as much as what gets executed.

The corresponding guarantees are the ones the plan states (§23): do not store
secrets, do not show the agent the hidden tests, do not let it modify the
dataset or the experiment, isolate workspaces and artifacts, keep manifests and
hashes, and never treat an agent's claim as an evaluation result.

## What is enforced today

### A workspace per run

`WorkspaceManager` (`src/akbench/datasets/workspace.py`) creates a git worktree
per run over a shared bare cache (`data/repositories`), detached from any
branch, from the task's pinned commit. Two runs of the same task never share a
directory — `isolation.workspace_per_run` cannot be set to `false` at all,
because two runs in one workspace contaminate each other. The mutation is
applied uncommitted, so the defect is not visible in the workspace's git
history.

The prepared workspace carries three fingerprints: the base commit, the
committed tree, and a working-tree fingerprint that includes the uncommitted
mutation. Two workspaces prepared from the same task description have the same
fingerprint, which is what makes a workspace repeatable.

### Hidden tests outside the agent

Hidden tests live in the task directory and are never part of the workspace
copy. Evaluation runs in a throwaway copy built by `evaluation_sandbox`
(`src/akbench/evaluators/isolation.py`): the produced workspace is copied, the
hidden tests are copied into that copy for the duration of the call only, and
the command runs there. `.git`, caches and other administrative names are
dropped by the copy. The agent's workspace stays byte-for-byte as the agent
left it, and the evaluator can never be modified by what it evaluates.

`diff_evaluator` is the one evaluator that reads the produced workspace
directly instead of copying it — a diff is a relation to the base commit, and
the sandbox deliberately drops `.git`, so the evaluator reads it read-only
(`docs/EVALUATORS.md`).

### Per-run agent state

The agent adapter owns its own isolation where the interface allows it. The
Codex adapter (`src/akbench/agents/codex.py`) gives every session a private
`CODEX_HOME` inside the run's artifacts — so no session, rollout, or cached
credential of another run is visible — and binds the run to the workspace,
with `sandbox_mode` a declared, controllable agent parameter. `fresh_agent_session`
and `clean_agent_context` are the experiment's policy, and the combination
"clean context without a fresh session" is refused by the descriptor.

### Memory isolation

A memory experiment must isolate more than the workspace: the replay arm must
see nothing of the learning arm except the written knowledge.
`src/akbench/knowledge/isolation.py` reports what a given deployment actually
isolates, per arm, including whether the **knowledge namespace** is isolated —
a property of the plugin and the deployment, not of the experiment author. On
the shared external router the namespace is not controllable, so experiments on
that instance share one knowledge namespace, and the report says so rather than
assuming the arms were independent. A managed instance is started with its own
prefixes, which is why memory experiments run managed
(`docs/KNOWLEDGE_REPLAY.md`).

Note what a namespace prefix does not do: stopping a router does not empty
Redis or the vector engine. Knowledge outlives the process that wrote it, and
the descriptor says so.

### Run artifacts and history

Each run writes to its own directory under `data/artifacts/<experiment>/<run>`,
records a checksum and size per artifact, and carries a reproducibility
manifest (`src/akbench/storage/manifest.py`). `akbench history verify RUN`
re-checksums the artifacts against the history and exits 1 on a mismatch. An
agent has no reason to touch another run's directory and no path that leads
there by convention — but that is a convention, not a wall: see the limits
below.

### Secrets

- **Descriptors are allowlists.** A component declares every variable it may be
  observed through (`observed_env`), and AK-Bench reads those names and no
  others; the environment of the process is never scanned
  (`src/akbench/descriptors/env.py`, `docs/PLUGINS.md`).
- **A secret is recorded as presence.** A `sensitive` entry is stored as
  `is_set`, never a value. The launch environment of a runtime keeps its
  secret-looking names the same way: the process gets the values, the record
  keeps the names.
- **The configuration does not hold credentials.** `AKBENCH_PG_PASSWORD` has no
  default and the settings field is a `SecretStr`, so dumping the settings does
  not carry it; the dashboard's users come from the environment, not from a
  file in the repository.
- **Exports are screened.** `src/akbench/export/redact.py` replaces matches
  with `[REDACTED:<kind>]` and reports the count; a secret is never masked in
  place, because a partially shown secret is still a secret. The switches in
  `src/akbench/export/filters.py` (`--no-prompts`, `--no-diffs`,
  `--no-traces`) leave whole classes of material out, and the export records
  what it left out (`docs/EXPORT.md`).

### The dashboard

`bench_ui` binds `127.0.0.1` by default and authenticates whenever it is not on
loopback (`AKBENCH_UI_AUTH`), because a benchmark's dashboard shows the answer
key. Hidden tests and the planted defect are a separate privilege from the
scoreboard: a `viewer` sees runs, scores and task prose; a `judge` may see the
ground truth, and even then only when the exposure switch allows it. Artifact
reads are confined to `AKBENCH_UI_ARTIFACT_ROOTS`. Authentication enabled with
no users configured is a startup error rather than a login box nobody can pass
(README, "Serving the dashboard").

## Docker: `deferred`

**The container isolation of plan sections 5, 14, 23 and 27 is not
implemented.** Phase B of the implementation plan is marked optional and was
not executed; `docs/ISOLATION_AND_SECURITY.md` is required by the plan to name
this explicitly, so here it is, in full:

- There is no `akbench/sandbox/` package, no `DockerSandbox`, no container per
  run, and no `isolation.sandbox: docker` option.
- The `docker-python312` Environment Descriptor (`descriptors/environments/`)
  declares the image, the ceilings and `network: false` **as intent**. Selecting
  it in an experiment is refused at validation
  (`environment_sandbox_unavailable`), because a run that asked for a container
  and quietly got the host would record an isolation it never had.
- `manifest.sandbox_image` is filled from the environment descriptor when there
  is one, and is `unknown`/absent on the host — an honest gap, not a guess.
- `doctor` reports Docker as an optional tool; nothing about a normal run needs
  it.
- The evaluation sandbox described above is a **copy into a scratch directory**,
  not a container. It protects the answer key and the produced workspace; it
  does not confine a process that decides to read the filesystem.

What host isolation actually consists of, today: a git worktree per run, a
private `CODEX_HOME`, the agent's own `sandbox_mode`, the copy-based evaluation
sandbox, and the run-directory and allowlist conventions above. That is enough
for the intended use — the operator's own machine, tasks the operator wrote,
agents the operator chose. It is not enough for the cases phase B was written
for: untrusted agents, a shared machine or CI, cross-machine reproducibility, or
published results with an environment guarantee. In those cases the missing
layer is the container, not a configuration flag.

## Experiment validity

Plan section 23 defines four experiment statuses, stored on the experiment
record (`storage/models.py`): `valid`, `valid_with_warnings`, `invalid`,
`incomplete`. The planner produces the first two — an error blocks the plan, a
warning stays in it — and reports say which they were, including the
"Not verified" table that lists every row whose configuration was not verified
(`docs/REPORTING.md`). Causes of invalidity are the ones the plan names: an
unverified configuration, missing capabilities, missing hidden tests, a bad
snapshot, or a knowledge base that was not ready.

## Limits: what AK-Bench does not guarantee

Stated plainly, because a benchmark that overstates its isolation is worse than
one that admits it:

- **No process-level confinement of the agent.** The agent runs as the operator's
  user, with the operator's read access to the filesystem, unless its own
  sandbox mode restricts it. Nothing in AK-Bench intercepts its syscalls.
- **No network control.** A router or an agent with network access has it; the
  `network: false` in the docker descriptor is a declaration with nothing
  enforcing it yet.
- **No resource ceilings.** Timeouts exist; CPU and memory limits do not. A run
  cannot be prevented from consuming the machine beyond its deadline.
- **No protection against a task's own content.** The `python_evaluator` script
  is a host subprocess, a task's setup commands would be too, and a task is
  trusted input by construction: the operator ships the dataset.
- **No multi-tenancy.** One operator, one project, one history. There are no
  users, no quotas and no ACLs on runs; the dashboard's roles control what a
  reader may see, not what a caller may do.
- **No claim that a recorded configuration was in force.** Where the interface
  cannot confirm a setting, the record says `unverified` or `unsupported`, and a
  report built on it is only as strong as that. That is the intended failure
  mode: an unverified configuration is visible, not hidden.

The rule that ties this page together is plan 23's last line: a declaration is
not a measurement. Isolation, configuration and results are all reported from
what was observed, and the places where nothing can be observed are the places
this page names as gaps rather than as features.
