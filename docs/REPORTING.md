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
  runtimes/index.html           one row per runtime
  plugins/index.html            plugin state across runs
  models/index.html             requested versus observed model
  assets/style.css
```

Commands:

- `akbench report all [--output DIR] [--json]` — the whole tree;
- `akbench report experiment UID [--output DIR] [--json]` — one experiment;
- `akbench report task UID [--output DIR] [--json]` — one task.

## What the dashboard shows

Experiment and run counts, the success rate with how many runs it rests on,
verdict breakdown, the leading configuration of every experiment, results
grouped by task category and difficulty, wall-clock time, token totals, a
per-agent, per-runtime, per-plugin and per-model comparison, and the recent
experiments.

Each experiment page adds a **Configuration ranking**: every variant with its
place, its success rate, mean time and token total, and its difference against
the declared baseline, followed by the same numbers drawn as bars. A place is
only stated for a configuration that has an evaluated run; a configuration
that was never scored holds no place rather than reading as a zero, and ties
share a place the way a competition ranks them.

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
