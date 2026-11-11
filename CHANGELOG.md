# Changelog

All notable changes to the `ak-bench` package are documented here.
Versions follow the `MAJOR.MINOR.PATCH` scheme; a new entry is added for every
release tagged as `v<version>`.

## Summary

| Version | Changelog                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
|---------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 0.1.2   | **Added:** the memory suite — thirteen expert tasks over four seeds (`atlas`, `tidewater`, `depweaver`, `walqueue`) built for one question: does a model that remembers do something a model that does not cannot? A learning task with antagonistic defect pairs plus exact-, related- and negative-transfer twins per seed; the new `tidewater` seed, a standard-library-only deterministic Raft-lite simulator with its own `SPEC.md`, ADRs, incident notes and trace-regeneration runbook; two new-feature pairs whose features are only finished once the repository's own generate/lock/digest procedure has been run; `configs/experiments/knowledge-replay-memory-suite.yaml` with the plugin mechanisms switched on per arm and a `knowledge_escalation_enabled` dimension for the ablation; isolated reference solutions under `tests/fixtures/` and an integrity suite per family. **Fixed:** a stray backtick in the atlas seed's package init that made every atlas mutation verification report an error, and the atlas memory experiment's arm and run-count assertions in the planner tests. |
| 0.1.1   | **Security:** dashboard authentication and roles, protected task answers and artifacts, hardened PostgreSQL configuration, response headers and input validation. **Added:** model verification indicators, themes, keyboard navigation, run export, tool-call metrics, task downloads and score charts, recorded task files and descriptors, agent and runtime pages. **Changed:** configuration labels, sortable tables, code and YAML viewers, PostgreSQL as the default database, automatic `.env` loading and SQLite-to-PostgreSQL migration. **Datasets:** the atlas sharded-store family — five `expert` tasks over one standard-library fixture (a five-module learning task, three single-defect twins in other modules, one new-feature task from a declared stub), a memory-replay experiment over six model × knowledge configurations with a no-memory baseline, and the knowledge scope pin that lets a replay read what its learning run wrote (an off arm is a process without the plugin). **UI:** model comparison on the dashboard — a Pareto chart and a paired base-vs-memory comparison with a delta heatmap, Wilson confidence intervals and low-sample marking on the model charts — and a full-page loading spinner.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| 0.1.0   | **Added:** the first release: the whole of AK-Bench, from the initial commit to now. A `typer` CLI (`akbench init/doctor/config`, experiments, datasets, runs, reports and exports); YAML/ENV configuration with an environment allowlist where secrets stay opaque (presence only, `src/akbench/config/`); a descriptor system with eight kinds — agents, runtimes, plugins, dimensions, models, categories, evaluators, metrics — versioned, digest-pinned and registered (`src/akbench/descriptors/`, `docs/DESCRIPTOR_SYSTEM.md`); tasks, datasets, repeatable workspaces, mutation verification and hidden tests (`src/akbench/datasets/`, `docs/DATASETS.md`); an agent-adapter framework with a Codex CLI adapter and capability gating (`src/akbench/agents/`, `docs/AGENT_ADAPTERS.md`); a runtime manager with direct/runtime/router execution, managed self-starting LLM Router instances with per-run port ownership and the instance log kept as a run artifact, plus model verification from that log (`src/akbench/runtime/`, `docs/RUNTIME_MANAGER.md`); a pytest/command evaluator engine with verdicts and hidden-test isolation (`src/akbench/evaluators/`, `docs/EVALUATORS.md`); a run orchestrator with a lifecycle state machine, isolation, retries and run records (`src/akbench/orchestration/`, `docs/RUN_ORCHESTRATOR.md`); an experiment descriptor and planner with matrix strategies, validation that refuses unmeasurable plans, factor routing by dimension source and environment bound to a combination (`src/akbench/experiments/`, `docs/EXPERIMENTS.md`); plugin observability — a run reports only the plugins it configured, with verification statuses (`src/akbench/plugins/`, `docs/PLUGINS.md`); knowledge replay for memory experiments (`docs/KNOWLEDGE_REPLAY.md`); SQLite storage, artifacts, a reproducibility manifest with digests, aggregates and baseline deltas (`src/akbench/storage/`, `src/akbench/metrics/`); a static HTML report — dashboard with a configuration ranking pooled across experiments, experiment/task/agent/runtime/plugin/model pages, a "Not verified" table and an in-report `docs/` subpage (`src/akbench/reporting/`, `docs/REPORTING.md`); JSON/CSV/HTML export with secret screening (`src/akbench/export/`, `docs/EXPORT.md`); shipped descriptors and eight experiment configs under `descriptors/` and `configs/experiments/`. |

## [Unreleased]

### Added

- **`configs/experiments/arena-roadmap-knowledge.yaml`**: the fifty new tasks in
  one arm — the managed local router, the `auto_codex` routing alias over the
  27B base model, and the knowledge plugin reading and writing (pipeline
  `agentic_routing_codex,agentic_knowledge`, `knowledge_enabled: true` applied
  to the process the run owns). `experiment validate` and `plan` are green:
  1 variant over the 50 tasks.
- **Fifty new tasks: the easy/medium/hard family and the roadmap task types.**
  The first ten are one `bug_fix` and one `new_feature` each over five new
  standard-library fixtures (`timetable`, `quiz`, `garden`, `playlist`,
  `cachekit`), filling the difficulty levels the dataset barely touched. The
  other forty are the seven task types the roadmap asked for — `debugging`
  (a defect the fixture suite never looks at), `security` (a vulnerability in
  the base code), `refactoring` (a declared target structure), `testing`
  (the agent writes the tests), `code_review` (a PR and a `REVIEW.md`),
  `performance` (correct but counted work) and `architecture` (a declared
  boundary) — each on its own standard-library fixture, with the seven
  categories enabled. Every task is proven by its integrity suite: each
  mutation `verified` with the seed suite green in both states, each missing
  feature `NotImplementedError` on the seed and complete under an isolated
  reference, and each roadmap task failing its hidden tests on the base
  fixture and passing hidden, public and fixture suites with its reference
  solution, which lives in the test files and never in a seed. The dataset is
  85 tasks; `akbench dataset validate` reports all of them.
- **Export filters: leave prompts, diffs or traces out on purpose** (plan
  section 21). `akbench export experiment` gains `--no-prompts` (the agent's
  own text: its final message, `last_message.txt`, and the prompt fields in
  records, replaced by `[withheld]`), `--no-diffs` (the produced change:
  `diff.patch` and siblings, `solution.zip`, and the diff fields in records)
  and `--no-traces` (the step-by-step record: `agent_trace.jsonl`,
  `tool_calls.jsonl`, `agent_traces.zip` and the stdout/stderr logs); the
  verdict, score and metrics stay, because they are the result. A reduced
  export says what it left out: `filters` names the closed switches and
  `withheld` counts the material by kind, so a reader knows the document is a
  subset. `--include-artifacts` copies what each run produced under
  `artifacts/<run uid>/`, with the same switches deciding what may be copied —
  a file filtered out of the document does not travel out as a file, and a
  surviving JSON record is stripped of the fields the switches name. With no
  flags the export is what it was: secrets screened, everything else as the
  run was.
- **The environment descriptor** (plan sections 9 and 14): a new `environment`
  kind (`descriptors/environments/`) stating where a run executes — OS,
  interpreter, tools, network, filesystem scope, sandbox kind, image and
  resource limits. Two are shipped: `local-host` (the honest statement of where
  AK-Bench runs today) and `docker-python312` (plan 14's container, declared
  before it is enforced). An experiment may name `environment: <id>`; the
  planner validates the reference, pins its digest in the plan's snapshots, and
  refuses a docker sandbox with the reason, because phase B's container is not
  implemented and a run that asks for one would otherwise happen on the host
  and record a container it never had. Runs carry their environment into the
  record and the reproducibility manifest, next to `sandbox_image`.
- **The scheduler: concurrency, resume, cancel** (plan section 15).
  `execution_policy.concurrency` is no longer ignored — `akbench experiment run`
  executes the matrix through a thread pool (an agent is a subprocess) and
  collects the results in plan order, not in the order the runs finished;
  `--concurrency` overrides the policy, and the plan warns when it is above one
  because N runs at once share the machine and the router.
  `akbench experiment resume UID` reads the plan back from the experiment file
  recorded with it and runs the matrix cells the history has no verdict for;
  `cancelled` counts as an operator asking rather than a result, so an
  interrupted cell is re-run and a finished experiment resumes to nothing.
  `akbench experiment cancel UID`, `Ctrl+C` in a running matrix, and a cancel
  in `run single`/`agent run` all stop the run in flight through one token: the
  agent is interrupted, the run is recorded `cancelled` with its artifacts kept,
  and no further cell starts. There is no daemon — the cross-process path is a
  marker file under `data/cancellations/`, documented as such.
  Preparing a workspace now holds a process-wide lock, because `git worktree
  add` on a shared bare cache is the one thing parallel runs must not race.
- **The commands of the plan's CLI sketch (§22) that were missing**:
  `experiment show UID` (plan, variants, runs and metrics read back from the
  history), `runtime start`/`runtime stop` (a managed instance outside a run,
  with an explicit refusal for `external`), `runtime verify [--expect k=v]`
  (health, the configuration triad, and the expected-versus-effective diff),
  `runtime status` (one runtime as `state`, or the whole registry), and
  `evaluator list` (the evaluators this installation actually implements).
  `docs/CLI.md` now carries a plan-versus-implementation table.

- **All five evaluators of plan section 16** (`docs/EVALUATORS.md`).
  `pytest_evaluator` and `command_evaluator` were already there; the three that
  had a descriptor and no code now do:
  - `diff_evaluator` — scores the overlap between the produced change and a
    reference patch, line for line, in the base coordinates both sides already
    carry. It reads the workspace read-only (a diff is a relation to the base
    commit, and the evaluation sandbox deliberately drops `.git`) and never
    reports `passed`: a diff is evidence about the change, not proof of
    correctness, so the verdict stops at `partial`.
  - `static_analysis_evaluator` — runs the analyser the task declares (ruff by
    default) over an isolated copy of the workspace and reports findings as a
    score: `passed` when nothing was found, `partial` when something was (a
    reason to look, not proof the task is unsolved), `infrastructure_error`
    when the analyser is missing, `evaluator_error` when its report is
    unreadable.
  - `python_evaluator` — runs a task-provided script in a separate process
    against an isolated copy of the workspace; the script reports through
    `evaluator-result.json` in `--out-dir`, and only the plan-16 vocabulary is
    accepted (a script cannot claim `infrastructure_error`). It is a host
    subprocess, not a security boundary, so a task must ship only a script its
    operator would run by hand.
  `akbench evaluate task` gained the inputs these evaluators need —
  `--reference-patch`, `--script`, `--command` — and an unknown evaluator id is
  still an explicit `EvaluatorNotFound`, never a stand-in.

### Fixed

- **Fresh-clone dataset integrity (Faza A planu do 100%).** The parts of a
  multi-defect mutation (`mutations/parts/*.patch`) are referenced by
  `parts.json`, so they are now a first-class part of a task: `6102769`
  removed the generic `parts/` `.gitignore` pattern and committed all 29
  patch files; `tests/unit/test_dataset_integrity.py` fails a checkout where
  a referenced part is missing from disk or from git.
- **The `data` directory is no longer a symlink** to the sibling
  `ak-bench-data` repository, which a fresh clone does not have (a dangling
  symlink broke `RepositoryManager` on a clean checkout). `data/` is now a
  plain, untracked directory created on demand by `akbench init` /
  `doctor`; historical data from the old location is imported with
  `akbench migrate sqlite …` (README Quick start documents this).
- **Audit and the 100% plan corrected against the code** (`.plans/`): the
  audit now carries a 2026-11-11 verification note — task and test counts,
  the commit it describes, and the two defects that do not exist in the
  current code (the atlas arm test and the live-router test are both green
  as written); the plan's source-plan path, §13 checklist reference, CLI
  paths, `default_registry` comment wording, and `full-matrix.yaml` strategy
  are fixed, and Phase A (A1–A5) is checked off with the evidence for each.

## [0.1.2] - 2026-11-10

### Added

- **The memory suite: thirteen expert tasks over four seeds, one question.**
  `configs/experiments/knowledge-replay-memory-suite.yaml` replays the suite
  with the knowledge plugin's mechanisms switched on per arm (and one ablation
  arm with them off): does a model that remembers — recipes, dead ends,
  playbooks and a documentation map carried over by the `agentic_knowledge`
  plugin — do something a model that does not cannot? The design rules are in
  `.plans/memory-suite-plan.md`; the tasks are `atlas-quorum-001..004`
  (learning, exact, related and negative twins of the quorum invariant),
  `atlas-schema-001/002` (a procedure pair over the schema tools), the new
  `tidewater` seed — a deterministic Raft-lite simulator — with
  `tidewater-election-001..003` (five election regressions all ending in one
  `election_safety` line, plus the related and the negative twin) and
  `tidewater-snapshot-001/002` (the node half of `SPEC.md` section 6 and its
  transfer half, each landing a corpus entry through the documented tools),
  `depweaver-lockfile-001` and `walqueue-compaction-002`. References for the
  new-feature tasks live under `tests/fixtures/`; integrity suites:
  `tests/integration/test_atlas_quorum_family_tasks.py`,
  `test_atlas_schema_family_tasks.py`, `test_tidewater_family_tasks.py`,
  `test_tidewater_snapshot_tasks.py`, `test_depweaver_lockfile_task.py` and
  `test_durable_dataset_tasks.py`.

## [0.1.1] - 2026-11-08

### Security

The dashboard was written to be read on the machine that started it and is now deployable elsewhere; these are the
consequences of taking that seriously.

- **The dashboard asks who is asking.** `bench_ui/security.py` and a small ASGI middleware put every route behind HTTP
  Basic, with two roles: `viewer` and `judge`. Authentication engages by itself unless the bind address is loopback, and
  an address the app cannot classify counts as exposed rather than private. Configured to authenticate with nobody in
  it, the command line refuses to start and a served app answers 503 — a module that raises on import reports nothing at
  all, which matters because uvicorn loads this one by import string. `/docs`, `/redoc` and `/openapi.json` are off. See
  `AKBENCH_UI_*` in the README.
- **A task's hidden tests and its planted defect are a separate privilege from its scoreboard.** Both were rendered and
  downloadable by anyone who could reach the port — the file tree, the descriptor's `mutation` section, and
  `GET /api/tasks/{uid}/download.zip` — which is the answer key of the benchmark. A `viewer` now gets the runs, the
  scores and the task prose; the descriptor they do see is reparsed with those two keys removed, and the archive is
  packed without those two kinds.
- **PostgreSQL is published on loopback, and the password has no default.** `scripts/run-postgres.sh` took
  `-p "${PORT}:5432"`, which binds every interface on the machine even while `AKBENCH_PG_HOST=127.0.0.1` read as "this
  box only"; publishing and connecting addresses are now separate variables. The bootstrap superuser's password was
  `akbench_local` in the code, the config and the example env at once, and connecting as that superuser made SQL access
  host access (`COPY … PROGRAM`, `pg_read_file`). There is no default to fall back on, a well-known value is refused,
  the password is a `SecretStr` so `config show --json` no longer prints it, and `AKBENCH_PG_APP_USER` provisions a role
  holding only the privileges AK-Bench uses. `env` and `start` no longer print the secret.
- **A recorded artifact path is read only inside directories the installation named.** `GET /api/artifacts/…` opened the
  path from the database row as given, so one writable row read any file the dashboard's own user could read — `.env`
  among them. Nothing was configured to name those directories before, so now there is `AKBENCH_UI_ARTIFACT_ROOTS`.
- **A page behind credentials is not cached, and every response carries security headers**: `Content-Security-Policy`
  (same-origin, which is also why Chart.js is vendored instead of loaded from a CDN a third party could substitute),
  `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`.
- **Two stored values stopped reaching `innerHTML` unescaped** — `run.status`, and the verdict-derived badge class, both
  free `VARCHAR(32)` columns. The class now comes from a fixed list, the way the server templates already chose it.
- **A request cannot ask for the whole database.** `limit` is bounded (and a negative one no longer means "everything"),
  the whole history is collected once per few seconds instead of several times per page, and the route handlers are
  synchronous so a database call runs on a worker thread instead of blocking the event loop: eight concurrent dashboards
  used to take 37 s in a strictly serial queue, one behind the other.
- **Namespace and `search_path` handling**: `validate_namespace` also runs in `create_namespace` and `_quote_schema`
  (whose docstring promised validation it did not have — it lived only in one CLI caller), the quote is escaped by
  doubling rather than assembled, and a namespace is checked before it is embedded in the libpq `options` startup
  parameter, where a space would append further `-c` settings to the session.
- **Smaller things**: a database error's text (host, port, user) no longer renders on every page and in a footer
  tooltip; `dotenv_path` is not sent to the browser; an engine-construction error names its URL with the password
  redacted; a JUnit report declaring a `DOCTYPE` or `ENTITY` is refused rather than expanded; a `LIKE` lookup escapes
  its wildcards; the run modal's `data-sort-value` attributes are escaped.
- **A freshly initialised database opens.** The dashboard ledger formatted four counters with `f"{value:,}"`, and a
  history in which no run reported tokens has `None` there, so an installation with nothing recorded answered its first
  visitor with a server error.

### Added

- **The atlas sharded-store family: five expert tasks over one fixture.**
  `datasets/_sources/atlas` is a standard-library-only sharded, replicated,
  fenced key-value store (roughly five thousand lines, twenty-four modules, a
  green 41-test suite, a normative `SPEC.md`, a 176-note incident corpus).
  `atlas-drift-001` breaks five of the store's invariants, one per module;
  `atlas-drift-002`/`-003`/`-004` are its twins, one regression each, in
  different modules, so a fix learned from the first transfers as a
  principle rather than a diff; `atlas-lineage-001` implements a declared
  feature (provenance, `SPEC.md` section 9) from a stub. The family is shaped
  for the memory experiment: the repository suite is green on the base and
  green after the mutation, the incidents name the rules by symptom, and each
  twin plants a plausible-but-wrong incident note. Integrity:
  `tests/integration/test_atlas_family_tasks.py`.
- **A memory experiment for the family, and the scope pin it needs.**
  `configs/experiments/knowledge-replay-atlas.yaml` runs one learning arm on
  the five-module task and replay/fresh controls for the same task plus the
  three twins, on six configurations: three requested models — two fixed (`qwen/Qwen3.8-27B`, `qwen/Qwen3.8-Flash-Next`)
  and the routing alias
  `auto_codex` — each run once with the knowledge plugin absent from the
  process and once present in it (an off arm is a process without the plugin,
  not a flag the process was asked to ignore), with the 27B model without
  memory as the baseline. The pipeline is declared per combination because it
  is read when the process starts: the alias arms load `agentic_routing_codex`
  (the alias means nothing without it) with the knowledge plugin joining only
  the arms that ask for it, and the fixed-model arms load nothing else. The
  plan is 4 tasks × 6 configurations = 24 runs, capped at `max_runs: 24` so
  an accidental dimension cannot multiply the bill. The knowledge plugin
  scopes collections by the checkout's directory basename, and AK-Bench named
  workspaces after the run, so a replay silently read a collection its
  learning run never wrote. The experiment runner now pins a memory run's
  checkout to `<run slug>/<repository name>`: unique per run, shared per
  fixture (`src/akbench/cli/experiments.py`,
  `tests/unit/test_knowledge_workspace_scope.py`), with the operator's
  alternative (`scope.overrides`) documented in `docs/KNOWLEDGE_REPLAY.md`.
- **Two corpus notes per twin family.** Six incident notes (`INC-2907`..`INC-2912`), each written about the symptom
  rather than the
  module, one of each pair recording the argument for the wrong fix — the
  reverted one-sided check, the ascending tie-break, the snapshot's own
  inclusive boundary.
- **The model charts say which models the runtime's log confirmed.** A model a run only asked for is weaker evidence
  than one the instance's log named it serving, so each model now carries how many of its runs were verified, shown
  beside its name on the charts, with a one-line note under them that says how much of the comparison rests on that kind
  of confirmation.
- **The dashboard compares the models against each other, not against an axis.**
  The model charts gained a synthesis row. The **Pareto chart** plots the
  success rate against a chosen cost axis — tokens, duration or tool calls, on
  a log or linear scale, the Y fitted to the data or held at 0–100% — and
  marks the Pareto front: the configurations no other beats on both axes at
  once, the rest left to the tooltip. The **paired chart** sets each model
  family (base model plus its served targets) against its own
  `+agentic_knowledge` twin on the same four measures, and the **delta
  heatmap** beside it puts every family × every metric in one table, green
  where the memory arm wins, red where it loses. The rows behind both are
  grouped by that family, so a baseline arm always sits beside its memory
  twin, and configurations nobody has evaluated yet are hidden behind a
  toggle rather than drowning the chart. The view controls fold into a menu,
  the toolbar is sticky while the grid scrolls, and the annotations stay
  inside the canvas.
- **A bar says how much to believe it.** The success-rate bars carry the
  Wilson 95% confidence interval of the pass rate — it stays inside [0, 1]
  and does not collapse to a point at 0 or 1, which is what makes it usable
  for the small samples a benchmark arm usually has — and a family with fewer
  than three evaluated runs is hatched and marked ⚠ n < 3, because a rate
  from one or two runs is not yet a measurement.
- **A page opens with a spinner, not a half-built page.** The full-page
  spinner is in the markup from the first byte, so the first paint of every
  page is the spinner; the script lifts it on load and puts it back the
  moment a link, a form or a `location` assignment takes the reader to
  another page. It holds for at least 200 ms, so a fast page does not
  flicker, and a navigation the browser cancels — a download, a blocked
  page, a Back pressed mid-flight — never fires `load()`, so a 12-second
  safety timer brings the spinner down either way. Whole-page transitions
  only: a fetch that repaints a table is the thin bar's business, and the
  spinner would hide what is already drawn.
- **A dark and a light palette, switchable from the navigation.** The theme is one swap of the variables the pages
  already read, so the markup and the component rules are untouched and the choice is remembered across pages. It is
  applied before the sheet paints, so a page never opens in the wrong palette, and the charts redraw when it changes
  because a canvas cannot follow a variable.
- **The runs table is driven from the keyboard.** Up and down move a cursor between the runs on screen, Enter opens the
  run under it, and `/` drops straight into the filter search. The row the cursor rests on is marked, so a reader moving
  with the arrow keys can see where Enter will land; the keys belong to whatever is being typed into, so the cursor
  stays out of the way of an input, a select and the run inspector.
- **The runs explorer copies its filtered rows out as CSV or Markdown.** Two buttons in the runs panel header take the
  rows the current filters match — refetched from the API, so a filter that has not repainted cannot export a stale
  answer — into the clipboard as a CSV for a notebook or a Markdown table for a message. The export carries the numbers
  the API holds (raw score, seconds, tokens), not the strings the page prettifies, and skips the columns that only drive
  the page (the comparison checkbox, the inspect button).
- **The UI shows what a run cost in calls, not only in tokens.** Every table that lists runs or configurations — the
  dashboard leaderboard and recent runs, the runs explorer, the task and experiment pages — carries a tool-calls column,
  with the raw number beside it so it sorts. The dashboard charts compare the models against each other on the same
  measures (success rate and score, duration and tokens) instead of one model against itself across metrics.
- **The dashboard opens with the overall picture.** Experiments, runs, evaluated, success rate, tasks, total time,
  input/cached/generated tokens and tool calls in one block, cost shown as "not recorded" until the history carries it.
- **A task's code is downloadable.** `GET /api/tasks/{uid}/download.zip` packs every recorded file under its kind, named
  `{task-id}__{version}.zip`.
- **The task page charts score per configuration** — one line per configuration over the task's runs in the order they
  started — and folds its long prose (the description) and its code tree away, so the definition is the first thing
  read.
- **The analytics explorer spins while it loads.** Every chart shows a loader until its data has been drawn, so an empty
  chart is not mistaken for a broken one.

### Changed

- **The two dashboard model charts wrap the configuration label.** Both panels took the label the previous change
  introduced, but a canvas does not wrap a tick: 74 characters of
  `auto_codex+agentic_knowledge[qwen/Qwen3.8-27B, qwen/Qwen3.8-Flash-Next]` ate the bar on the horizontal chart and
  collided with its neighbours on the vertical one. A tick is now a list of lines, broken at the separators that already
  mean something in the label — before a plugin, between two served models — never inside a name, and each panel grows
  by the extra lines so nothing is clipped.
- **A run is named by the configuration it ran, not by whatever the router resolved to.** A run that asked for the alias
  `auto_codex` was listed under `qwen/Qwen3.8-27B, qwen/Qwen3.8-Flash-Next` — the two models routing chose between, read
  by anyone else as a third model nobody asked for. The table, its model filter and the comparison charts now share one
  label: the model asked for, each plugin that was on, then what actually served in brackets
  (`auto_codex+agentic_knowledge[qwen/Qwen3.8-27B, qwen/Qwen3.8-Flash-Next]`). A model asked for and served as named
  keeps its bare name, a run no log confirmed keeps the alias alone, a plugin that was off is not named at all, and cost
  estimation still reads the real model rather than the label.
- **The dashboard's recent-runs and leaderboard tables repeat the run's repetition number** beside the other run
  columns, and every table that lists runs shows it.
- **Code viewers offer a copy button beside close** in the task code viewer and the run modal, so the text shown can be
  taken without selecting it.
- **YAML in the UI is coloured.** The recorded descriptors (task, experiment, agent, runtime) and the task's
  `description.md` get a light syntax highlight for keys, values and comments.
- **The runs explorer shows which tests passed and which failed in a run.** The inspect modal lists the evaluator's
  per-test results — green for a pass, red for a fail — when the run recorded them, alongside the passed/failed/total
  summary.
- **Numeric table columns sort both ways.** A cell's sort value is its own text, or the text it shows when it has none;
  a cell that opens with whitespace and nests its number in a span used to sort on nothing, which is why success rate,
  mean score and the against-baseline columns never moved. The against-baseline column now sorts on the success-rate
  difference it describes.
- **The runs explorer keeps its two-run comparison budget visible.** Selecting two runs dims the rest and disables their
  checkboxes, and the state survives filtering; the run diff opens on two runs chosen from lists of the same runs.

- **A task's code is recorded in the history and browsable in the UI.** `task_files` stores the repository a task is
  worked in, its hidden and public tests and its mutation patch, one row per file with a size and a `sha256` digest
  (migration `0010`); binary files and anything over 256 KB are left out rather than stored empty. The task page shows
  the code as an expandable directory tree grouped by kind, and clicking a file reads its text from
  `GET /api/tasks/{uid}/files` and `GET /api/tasks/{uid}/files/{path}`. `scripts/update_task_info.py` backfills the
  files of an existing history from the dataset on disk.
- **Agents and runtimes are first-class rows, filterable in the UI.** `agents` and `runtimes` keep every version a run
  was made of, keyed by the id the run already recorded, each with the descriptor file it declared (migration `0009`).
  New `/agents`, `/agents/{id}`, `/runtimes` and `/runtimes/{id}` pages show the descriptor as written — capabilities,
  controllable configuration, execution modes, endpoints — and the runs explorer filters by agent and by runtime.
- **An experiment carries its own descriptor.** `experiments.experiment_yaml` is the file the experiment was planned
  from, and its page shows a configuration panel read from that file plus the raw YAML, so an experiment explains itself
  without its checkout.
- **Every table sorts by clicking its column header.** First click ascending, second descending, a double click restores
  the page's own order; formatted cells (`1m 30s`, `1.2 MB`) sort by the value they show, and a table rendered after
  load arms itself through `window.akbenchSortTables()`.
- **Task content is recorded in the history and shown in the UI.** Every task row now stores what the task asks — the
  title, the one-line description, the full `task.yaml` descriptor and the task's `description.md` (migration `0008`).
  The UI answers a task page from the history alone: the task catalog shows titles, descriptions, authors and timeouts,
  and the task detail shows the definition with constraints, setup, mutation and repository, the full scope of work, and
  the recorded descriptor. When a task was recorded before its content was stored, the dataset on disk fills the gap and
  the page says the definition came from there.
- **`scripts/update_task_info.py` backfills an existing history** with the task content from the dataset on disk
  (migrating the schema to head first), for the PostgreSQL the project is already using.
- **The UI footer links [radlab.dev](https://radlab.dev) and [llm-router.cloud](https://llm-router.cloud/).**

### Changed

- **PostgreSQL is now the default database.** Recorded benchmarks go to PostgreSQL instead of the SQLite file, so a
  project has one shared, server-backed history. SQLite stays available as an explicit fallback for a laptop without a
  server.
- **A project `.env` file is read automatically.** The same `AKBENCH_PG_*` connection names `scripts/run-postgres.sh`
  uses now configure the engine; an exported variable beats the file, and `AKBENCH__DATABASE__*` still overrides both.
  The connection URL is redacted (password hidden) everywhere it is displayed, in `akbench config show` and in the UI
  footer.
- **`akbench migrate` imports a SQLite history into PostgreSQL, one namespace per file.** Several working directories
  share one server; each import lands in its own schema (read back with `AKBENCH__DATABASE__POSTGRES__NAMESPACE`),
  children after parents, every table counted on both sides, and a difference is an error. The import surfaced a real
  defect: `config_hash` was declared 64 characters while the code has always written `sha256:<64 hex>` (71) — SQLite
  never enforced the length, PostgreSQL does. The column is now what the code writes (migration `0007`).

### Fixed

- The atlas task descriptors' titles and constraints carried a bare `:` in a
  plain YAML scalar; they are quoted, so `akbench dataset validate` reads all
  twenty-two tasks.
- The dashboard ledger reported a mean time over runs of different lengths;
  one average there says less than the total it was derived from, so it left
  the summary block.
- The atlas experiment's fixed-model arms loaded the routing plugin without
  asking it for anything — a fixed model asks nothing of the router; the
  pipeline is now the knowledge plugin alone on the arms that want it, and
  the alias arms carry `agentic_routing_codex` with the knowledge plugin
  joining the arms that ask for it.

## [0.1.0] - 2026-11-05

### Added

- **CLI and configuration.** A `typer`-based CLI (`src/akbench/cli/`) with `akbench init`, `doctor`, `config`, dataset,
  experiment and run commands; YAML configuration loaded with Pydantic plus an ENV layer where the environment allowlist
  treats secrets as presence-only, so a key's value never enters a descriptor (`src/akbench/config/`, `docs/CLI.md`).
- **Descriptor system.** Eight descriptor kinds — agent, runtime, plugin, dimension, model, category, evaluator,
  metric — each versioned and digest-pinned in a registry, so a recorded run pins exactly the descriptors it ran under
  (`src/akbench/descriptors/`, `docs/DESCRIPTOR_SYSTEM.md`, shipped descriptors under `descriptors/`).
- **Datasets and tasks.** Task descriptors, dataset validation, git-based repeatable workspaces, mutation verification
  of task sources and hidden tests that an agent never sees (`src/akbench/datasets/`, `docs/DATASETS.md`, `datasets/`
  with twelve task repositories and the shipped task sets, including the very-hard implement and bugfix tasks).
- **Agent adapter framework.** A capability contract, a registry, and the Codex CLI adapter with capability gating and
  contract tests, so a new agent is a module, not a fork (`src/akbench/agents/`, `docs/AGENT_ADAPTERS.md`,
  `docs/AGENT_INTEGRATION.md`).
- **Runtime manager.** Execution modes — direct, runtime, router — managed versus external lifecycles, an LLM Router
  adapter, the configuration triad, and a managed instance launched per run with its own environment, port ownership,
  and the instance log kept as a run artifact; the requested model is verified against the models the instance's own log
  attributes requests to (`served_models`, `routing_decisions`, `received_models`) with statuses `verified`/
  `unverified`/`mismatch`/`unsupported`/`not_configured`/`runtime_error` (`src/akbench/runtime/`,
  `src/akbench/runtime/llm_router.py`, `docs/RUNTIME_MANAGER.md`, `docs/ROUTER_INTEGRATION.md`).
- **Shipped runtimes and experiments.** A managed `llm-router-ak-bench` runtime (self-start) and a shared
  `llm-router-external` runtime, the `agentic_knowledge` and `agentic_routing_codex` plugin descriptors, and eight
  experiment configs: `full-matrix`, `knowledge-on-off`, `knowledge-replay`, `llm-router-external-fast`,
  `llm-router-selfhost-fast`, `model-comparison`, `router-config-comparison`, `wordcount-direct-sanity`.
- **Evaluator engine.** Pytest-based and command-based evaluators, isolation of hidden tests from the agent's workspace,
  and verdicts per run (`src/akbench/evaluators/`, `docs/EVALUATORS.md`).
- **Run orchestrator.** A lifecycle state machine (`pending` to `completed`, with terminal `failed`, `timeout`,
  `cancelled`, `infrastructure_error`, `invalid_configuration`, `evaluation_error`), per-run isolation, retries, and run
  records; a blocking run reports where it spends its time, and a run can report its transitions to an observer
  (`src/akbench/orchestration/`, `docs/RUN_ORCHESTRATOR.md`).
- **Experiments and planning.** An experiment descriptor, matrix strategies, validation that refuses — rather than
  degrades — a plan it cannot measure, routing of factors to their destination by a dimension's `source`, and a binding
  of a factor combination to the environment its runtime starts with (`src/akbench/experiments/`,
  `docs/EXPERIMENTS.md`).
- **Plugin observability.** A plugin adapter that reads plugin state only from an allowlisted environment and only from
  the environment the run itself launched, an `enabled_when` toggle, and verification statuses; a run reports only the
  plugins it configured (`src/akbench/plugins/`, `docs/PLUGINS.md`).
- **Knowledge replay.** Memory experiments with learning/fresh arms and a readiness gate (`src/akbench/knowledge/`,
  `docs/KNOWLEDGE_REPLAY.md`).
- **Storage and metrics.** SQLite with Alembic migrations, a history of repositories and tasks, artifacts, a
  reproducibility manifest with digests, aggregates, and baseline deltas (`src/akbench/storage/`,
  `src/akbench/metrics/`, `docs/STORAGE.md`, `docs/METRICS.md`, `docs/REPRODUCIBILITY.md`).
- **Reporting.** A static HTML report: a dashboard with the configuration ranking — one row per configuration (factor
  values + agent + runtime) pooling all of its runs, mean-per-run tokens and tool calls, places shared across
  experiments — plus experiment, task, agent, runtime, plugin and model pages, a "Not verified" table, and a `docs/`
  subpage rendering the project's own markdown with a styled menu (`src/akbench/reporting/`, `docs/REPORTING.md`).
- **Export.** JSON/CSV/HTML export with secret screening so an export never carries a credential (`src/akbench/export/`,
  `docs/EXPORT.md`).
- **Documentation.** `README.md` with a step-by-step guide to how AK-Bench reads a configuration, and one doc per
  subsystem under `docs/` (descriptor system, datasets, agent adapters, runtime manager, evaluators, run orchestrator,
  experiments, plugins, knowledge replay, storage, metrics, reporting, export, reproducibility, development, CLI).
