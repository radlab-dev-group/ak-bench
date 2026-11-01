# Reporting

`akbench report` writes the recorded history out as a tree of static HTML
files: no server, no JavaScript, no external asset. Open `index.html` and it
works from a USB stick as well as from a web server.

```
data/reports/
  index.html                    dashboard
  experiments/<uid>/index.html  one page per experiment
  tasks/<uid>/index.html        one page per task
  tasks/index.html              every recorded task
  agents/index.html             one row per agent identity
  agents/<slug>/index.html      the runs of one agent, with their parameters
  runtimes/index.html           one row per runtime
  runtimes/<slug>/index.html    the runs of one runtime
  plugins/index.html            plugin state across runs
  plugins/<slug>/index.html     the runs a plugin was observed in
  models/index.html             requested versus observed model
  models/<slug>/index.html      the runs that asked for a requested model
  categories/index.html         one row per task category
  categories/<slug>/index.html  the runs of one category
  difficulties/index.html       one row per difficulty
  difficulties/<slug>/index.html the runs of one difficulty
  verdicts/index.html           one row per verdict
  verdicts/<slug>/index.html    the runs that carry a verdict
  runs/index.html               every recorded run, newest first
  runs/<uid>/index.html         one run, in full
  assets/style.css
```

Commands:

- `akbench report all [--output DIR] [--json]` — the whole tree;
- `akbench report experiment UID [--output DIR] [--json]` — one experiment;
- `akbench report task UID [--output DIR] [--json]` — one task.

`report all` reads the dataset directory from the configured paths when it
exists, so task pages carry the task's definition; the experiment and task
single-page commands do the same.

## What the dashboard shows

Experiment and run counts, the success rate with how many runs it rests on,
verdict breakdown, the ranking of every recorded configuration, results
grouped by task category and difficulty, wall-clock time, token totals, a
per-agent, per-runtime, per-plugin and per-model comparison, and the recent
experiments.

**The dashboard ranking is one row per configuration.** A configuration is the
factor values together with the agent and the runtime that ran them, so the
same values under another agent, or on another runtime, hold their own row.
Everything else is pooled into the one row: the second recording of an
experiment, and the same configuration recorded in another experiment, both
add their runs to it. The success rate is therefore pooled — the passes over
the evaluations of all those runs, not an average of the recordings — and the
**place is stated over the pooled runs**, which is what lets one row answer
which configuration won across the whole history. Because the recordings are
pooled, a row states where it came from: the **experiments** it was recorded
in (the first linked, the rest counted) and how many **recordings** it merged,
over what task set and what window of time. Two recordings need not share a
task set, a model or a day, and the note under the table says so rather than
hiding it behind a merged number. The token and tool-call columns of a ranking
are **means per run**, not sums: a sum over a different number of runs is not
a number to compare, and a run whose agent reported nothing stays missing
rather than reading as zero.

Each experiment page adds the same **Configuration ranking** over its own
recordings: a row pools the variants that carry one configuration — the same
values run by the same agent on the same runtime — so two recordings of an
experiment that planned the same values twice become the one row they
describe, counted over all of their runs, with the same means-per-run token
columns and its difference against the declared baseline, followed by the same
numbers drawn as bars. A place is only stated for a configuration that has an
evaluated run; a configuration that was never scored holds no place rather than
reading as a zero, and ties share a place the way a competition ranks them.
The **recording** column of a row states how many recordings it pooled, which
tasks it rests on and the start-to-finish window of the runs it was measured
in.

**Run tables carry their own context.** Every run table — on the task, the
experiment and the agent, runtime, plugin and model pages — shows the factor
values the run was executed under, when it started, and its repetition, so a
row of numbers is not a list of unexplained results. Runs are listed in the
order they started, and a long verification note is folded to one line with
its full text kept in the document.

**Every label is a page.** A row on the dashboard is a link only to a page
that exists: verdicts, task categories, difficulties, agents, runtimes, plugins
and models each have a detail page, and the run uids in every table link to the
run's own page. A link that pointed at a page that was never written is a
broken promise, so the report is checked that no href is a dead end.

**The page is as wide as the window.** A run table is fourteen columns of
numbers, so the report takes the width the window gives it, up to a cap that
exists only to keep an ultrawide monitor from scattering one row across a
metre of glass. A narrow window keeps a readable floor. Prose is the one thing
that does not stretch: task descriptions and notes stay at a measure that can
be read across without tracking a line back.

**Wide tables fit the page.** A table is marked with a density class from its
own column count (ten columns and up tighten the type, thirteen and up
tighten it further). The number columns hug their content, the text columns
take what is left and wrap, and every text column keeps a floor below which
the wrapper scrolls instead of the row having to be read by scrolling back and
forth.

**Run tables sort.** Clicking a column header of a run table reorders its rows
by that column — the one exception to the no-scripting rule, and a small,
self-contained script that ships in the page, not an external asset. Clicking
the same header again flips the direction: the first click sorts ascending,
the next descending, and so on, with the applied direction marked on the
header. It reorders rows and nothing else: no number is computed or fetched, a
value that was never measured sorts last rather than as zero, and a page read
with scripting off still shows every row, in the order the history recorded.

**Tokens are stated as they were paid.** Every table that reports a token
total splits it the way the agent reported it: input tokens, generated tokens
and the total the two add up to, plus the tool calls the agent made. A column
with no measurement in its runs shows a dash, not a zero — the agent reported
nothing, and reporting nothing is not the same as reporting zero.

**A run has its own page.** A run page states where the run belongs — the
experiment, the task, the configuration it was executed under, the agent, the
runtime, the repetition — and then everything the record holds: the verdict and
the score with how many tests passed, failed and were total; what the agent
reported (the wall clock, the tokens, the tool calls, the exit code, any error);
the model requested and observed, and the plugins observed next to the run, with
their verification; and the paths and checksums of the artifacts the run left
behind.

**A subject page answers where it was.** An agent, runtime, plugin, model,
category, difficulty or verdict page lists, before the runs, the experiments
the subject took part in and the tasks it worked, so the runs below have their
context instead of reading as an isolated list.

**A task page is the task, not only its history.** Beyond its runs, a task
page prints what the task asked: the title, the short description, the full
markdown description, the constraints, the notes, and the recorded identity —
the evaluator, the timeout, the tests, the repository and the snapshot
digest. The prose is read from the dataset directory at report time, because
the database holds the task's identity and digest, not its wording. If the
digest of the definition on disk differs from the snapshot the runs were
recorded with, the page says the two do not match; a report written where the
dataset directory is absent or unreadable still writes, and its task pages say
the definition is not available.

## Rules the reports obey

- **Nothing invented.** A report is a rendering of what the database holds.
  An average states how many runs produced a value, and a value that was never
  measured prints as `not measured` rather than reading as zero.
- **Cost is not a number here.** The project records tokens, not prices. The
  cost block says so instead of multiplying tokens by a made-up rate.
- **Failures stay visible.** A run that failed, timed out or broke the
  infrastructure is rendered in the runs table and again under *Not passed*;
  it is never filtered away.
- **Unverified stays flagged.** Every plugin or model observation whose
  `verification_status` is not `verified` is listed on the dashboard and on
  the affected experiment and task pages, with the run it belongs to.
- **Everything is escaped.** Run records contain agent output; it is HTML-
  escaped before it reaches the page.

## Source

The data lives in `src/akbench/reporting/data.py` (what a number means and
where it comes from) and `src/akbench/reporting/render.py` (how it becomes a
page). The CLI is `src/akbench/cli/report.py`. The history reads the reports
use are on `akbench.storage.history.HistoryStore`.

The report tree is generated from the recorded history plus, when the dataset
directory is present, the task definitions it holds. A link integrity check is
part of the test suite: every href in every written page is resolved, and a
page that points at a file that was never written fails the build.
