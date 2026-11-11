# Factorial design

The planner turns an experiment's factor declaration into variants with a
strategy from `src/akbench/experiments/strategies.py` (implementation plan,
section 12.2). Five strategies are implemented, every one of them
deterministic, and each is a pure function from `(factors, baseline, selected)`
to a list of assignments — no agent, no workspace, no clock. This page is what
each strategy generates, how the baseline and deduplication work, and how the
cost of a plan is estimated and bounded.

## The shape

A factor is a resolved dimension with the values this experiment varies
(`Factor`: `id`, `descriptor`, `values`; `docs/DIMENSION_DESCRIPTORS.md`). An
assignment is a mapping `factor id -> value`. A strategy returns assignments;
the planner turns each into a `PlanVariant` with a stable id, a config hash and
a baseline flag, and the counts follow: `runs = tasks × variants × repetitions`.

```bash
akbench experiment plan configs/experiments/full-matrix.yaml
akbench experiment plan configs/experiments/full-matrix.yaml --variants --json
```

The plan prints the four numbers, the estimate, and the validation findings —
before anything is started.

## The five strategies

`strategy_for(name)` resolves the name from `factors.strategy`; an unknown name
is an error naming the known strategies.

### `full_factorial`

The cross product of every factor's values. Two factors with two values and a
third with three give twelve variants, in a stable order (the cartesian
product of the declared value orders). With no factors at all the result is a
single empty assignment — the sanity case, where the whole experiment is one
configuration.

This is what `full-matrix-12.yaml` uses: memory × routing × model = 12
configurations, expanded rather than written out.

### `selected_factors`

Only the factors named in `factors.selected` vary; every other declared factor
is pinned to its baseline value. Naming no selected factor, or naming one that
is not declared, is an error — naming what varies is the whole point of the
strategy.

### `one_factor_at_a_time`

The baseline first, then exactly one changed factor value at a time. The
baseline must be declared for every factor and must be a value the experiment
varies (`BaselineMissingError`, `BaselineValueError`), and it must be the first
variant: a one-factor-at-a-time run built on some other reference answers a
different question than the one the experiment declares. With three boolean
factors whose baseline is all-`false` the result is the baseline plus three
variants, not eight.

### `pairwise`

A greedy covering array: every pair of values from every pair of factors
appears in at least one variant. Greedy rather than optimal on purpose — these
matrices are tens of variants, and a deterministic greedy pass is easier to
audit than a search whose result depends on luck. Each uncovered pair seeds a
variant whose remaining factors take the value that covers the most pairs still
missing. One factor degenerates to its values.

### `custom_matrix`

Exactly the declared `combinations`, in that order. Every factor not named in
a row takes its pinned value (below), and a row that names a value outside the
factor's declared set is refused with the row's position. A row may also carry
the reserved key `runtime_env` — the environment that variant's runtime process
starts with — which is not a factor value and is taken out before the matrix is
expanded (`docs/RUNTIME_ADAPTERS.md`).

This is the strategy to use when a configuration is not a value.
`full-matrix.yaml` writes its rows out precisely so that its "off" arm is a
plugin *absent*, while `full-matrix-12.yaml`, expanded by `full_factorial`, has
an "off" arm that is a plugin *present and switched off*. Two different
questions, and each file says which it asks.

## Baseline and pinned values

`pinned_value(factor, baseline)` picks, in order of preference:

1. the experiment's `factors.baseline` value for the factor;
2. the dimension descriptor's `default`;
3. the factor's first declared value.

All three are declared facts; none is invented. Strategies that pin factors
(`full_factorial`, `pairwise`, `selected_factors`) check that the pinned value
is one of the factor's values, and `custom_matrix` refuses a row where it is
not.

The baseline also marks the reference variant: `_matches_baseline` compares the
assignment against `factors.baseline` with types strict (a baseline of `false`
is not matched by `0`), and the flagged variant is what the report's deltas are
computed against. A declared baseline that appears in no variant is an error
(`baseline_not_in_matrix`) — a comparison without a reference answers nothing —
and no baseline at all is a warning (`baseline_undeclared`), except in a
`knowledge_replay` experiment, whose reference is its fresh arm.

## Deduplication

`one_factor_at_a_time` and `pairwise` pass their output through `_deduplicate`,
which drops assignments that are equal to an earlier one (by canonical JSON of
the assignment, so `1` and `true` are not the same value) and keeps the first
occurrence. `custom_matrix` deduplicates too: two rows that mean the same
configuration are one variant, and the plan should not pretend otherwise.
`full_factorial` and `selected_factors` do not need it — the cross product
cannot repeat — and so do not get it: a strategy that deduplicates what cannot
repeat hides a factor declared twice.

Duplicate factor ids are refused by the experiment descriptor before a strategy
ever runs, and a dimension resolved with duplicate values is an error at
resolution.

## Cost, limits and what the plan refuses

The estimate is deliberately not a prediction
(`PlanEstimate` in `src/akbench/experiments/planner.py`):

- `run_seconds_upper_bound` is the declared `execution_policy.timeout_seconds`;
- `total_seconds_upper_bound` is that times the number of runs;
- with no timeout declared, both are `null` and the basis says why — an upper
  bound from a declared timeout is a fact about the configuration, a forecast of
  how long an agent will take is not.

`experiment.limits` bounds the plan (`docs/EXPERIMENT_DESCRIPTORS.md`):
`max_runs`, `max_variants`, `max_tasks`. Exceeding one is an error
(`limit_runs`, `limit_variants`, `limit_tasks`) and blocks the run: the point of
a limit is that a mistaken matrix must not start, and every shipped experiment
declares one.

Strategy failures arrive as validation errors with the strategy's own code
(`strategy_failed`, `baseline_value_invalid`, plus the messages above), so a
matrix that cannot be built is reported as a plan problem with a reason, not as
an experiment that ran with something else.

## Choosing a strategy

| Situation | Strategy |
|---|---|
| Every combination matters, and the product is affordable | `full_factorial` |
| One or two factors matter and the rest must merely be pinned | `selected_factors` |
| A cheap scan over many factors, with the baseline as reference | `one_factor_at_a_time` |
| Interactions matter but the full product does not fit | `pairwise` |
| The arms are specific configurations, each with its own process environment | `custom_matrix` |

The estimate and the limits are the negotiation: pick the strategy that answers
the question with as few runs as it needs, declare the ceiling, and let the
planner refuse when the two disagree.
