# Write the schedule that three of the quorum rules are load-bearing for

`src/tidewater/membership.py`, `src/tidewater/node.py` — three of the places
where this cluster decides that a majority has spoken have been weakened. Each
one is a single expression, each is invisible to the repository suite, and each
turns a partition into lost or contradictory commits:

| id | where | what went wrong |
| --- | --- | --- |
| `minority-quorum` | `Configuration.majority_size` | "strictly more than half" became "half", so two of five can elect and commit |
| `commit-no-quorum` | `Node._advance_commit_index` | an entry is committed once the leader holds it, without waiting for a majority of `match_index` |
| `stale-term-append` | `Node._handle_append_entries` | a follower no longer refuses an `AppendEntries` from a term below its own |

Twelve generated schedules ship in `schedules/` and not one of them catches any
of the three. Your job is not to fix the simulator — it is to write the chaos
schedule and the test that prove each of the three rules matters.

## Deliver

1. `chaos/byzantine-partition.json` — one schedule, declarative, schema 1.
2. `tests/test_chaos_schedules.py` — loads that file with
   `tidewater.schedule.load_schedule`, runs it through
   `Cluster(schedule, stop_on_violation=True)`, and asserts that the run
   finishes with **no** violation and that the cluster committed work.

Both files are graded. The harness runs your test against the simulator as it
stands (green, or the whole task scores nothing) and then against a copy with
each of the three defects applied (each has to fail).

## How to think about it

- `docs/schedule-spec.md` is the action language: `partition`, `heal`, `crash`,
  `restart`, `isolate`, `block`, `skew`, `network`, `workload`, `propose`.
- A defect that lets a pair elect or commit on its own is only visible if the
  pair is actually **left alone** — cut off from the other three for longer than
  `election_timeout` ticks — and then **healed**, because the disagreement only
  becomes a violation when the two halves meet again. A schedule that partitions
  for twenty ticks proves nothing.
- The invariant monitor (`src/tidewater/invariants.py`) is the oracle: it raises
  `leader_completeness`, `state_machine_safety` or `election_safety`. Your test
  does not have to name which one fires; it has to fail when one does.
- Committed work matters: a schedule that never commits cannot lose anything, and
  a run that never elects cannot contradict itself. Assert progress, or your
  green test is an accident.
- Read `schedules/partition-minority.json` and `schedules/partition-heal-storm.json`
  for the shape, then write your own. `tools/gen_schedules.py --check` must stay
  green, which is why your file goes in `chaos/`, not in `schedules/`.
- Determinism is the whole point: same seed, same run. If your schedule only
  catches a defect sometimes, it catches nothing.

## Boundaries

- Do not modify `src/`, `tools/`, `traces/`, or anything under `schedules/`.
- The repository suite (`python -m pytest tests/`) stays green.
- Standard library only.
