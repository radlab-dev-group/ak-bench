# Metrics and Observability

AK-Bench reports what a run actually produced (plan section 18). The metric
catalog is data — Metric Descriptors — and every metric states whether it can
be computed. A metric without a source is `unavailable` with a reason, never
zero: zero would be a claim the evidence does not support.

## Groups

| Group | What it measures | Decides the outcome? |
|---|---|---|
| `quality` | verdicts, hidden-test pass rate, regressions, evaluator score | yes |
| `efficiency` | wall time, tokens, tool calls | no — reported, never a success criterion |
| `agent_runtime` | agent identity, session id, run status, observed model | no |
| `knowledge` | writes, retrievals, hit rate, latencies, KB size | no — `unavailable` today (see below) |
| `reliability` | timeouts, infrastructure failures, agent crashes, trace completeness | no — separates environment from agent (rule 11) |

## Honesty rules

- **A measurement, not a statement.** A metric is `measured`, `derived` or
  `unavailable`. The availability of every value in every report says which of
  the three it is.
- **Unavailable is not zero.** `knowledge_hit_rate` is `unavailable` while the
  router exports no per-plugin counter. Reporting `0` would read as "the
  knowledge layer was not used".
- **A rate is computed only over the runs that reported the value.** The
  measured count and the availability share are printed next to every mean, so
  an average over two of ten runs cannot masquerade as one over ten.
- **A crash is not a failed task.** A non-zero exit code alone is not a crash:
  an agent that fails a task also exits non-zero. A crash is an agent-side
  failure that ended the process abnormally (a signal, or a broken stream).
- **Cheaper is not better.** A faster or cheaper variant is reported with the
  quality metrics next to it, so an efficiency gain can never be read as
  success on its own.

## Baseline comparison

Deltas follow the plan's formulas:

- `delta_success = success_variant - success_baseline`
- `speedup = time_baseline / time_variant`
- `token_saving = 1 - tokens_variant / tokens_baseline`

When a baseline is zero the absolute difference is reported instead, because a
ratio against zero has no meaning. When a side has no value, the delta is
`null` with a note saying which side reported nothing.

## Collection

`collect_run_metrics` reads a plain run record — the same shape
`akbench run` writes to `run_record.json` — plus the agent observations and
any plugin or runtime values a caller has. It works on a live run and on a run
loaded from disk.

## CLI

| Command | Description |
|---|---|
| `akbench metrics catalog [--group G] [--json]` | the metric catalog with the availability of every metric |
| `akbench metrics run RECORD [--baseline B] [--json]` | aggregate the metrics of recorded runs, with baseline deltas |

## What is deliberately not here yet

- The knowledge and routing plugin metrics stay `unavailable` until the router
  exports per-plugin counters or a readback of the KB state exists.
- `router_error_rate` is only reported when a caller supplies runtime
  observations, because the router counter is global to the shared instance
  and describes the environment, not the run.
