# Runbook: regenerating the schedule corpus and the reference traces

This is the procedure `CONTRIBUTING.md` points at. It exists because two
kinds of generated artefacts live in the repository and both have locks:

* `schedules/*.json` — twelve fault schedules produced by
  `tools/gen_schedules.py` from one root seed, locked by
  `schedules/MANIFEST` (SHA-256 of each file);
* `traces/*.digest` — one reference digest per schedule produced by
  `tools/reference_traces.py`, each recording the schedule's own digest,
  seed, tick count, event counts and the trace digest.

`--check` on either tool is what the repository suite and CI run. A red
check is a question — *did you mean to change this?* — and this runbook is
how you answer it.

## 0. Before you start

```
python tools/gen_schedules.py --check
python tools/reference_traces.py --check
```

Both must be green on a clean checkout. If they are not, stop: somebody
left the repository in a state this runbook assumes away, and the first job
is to find out which commit did it (`git log -- schedules traces`).

Run every tool from the repository root. The tools add `src/` to
`sys.path` themselves; `PYTHONPATH` is not needed for them (it *is* needed
for `python -m tidewater` and for `pytest`).

## 1. Decide which of three situations you are in

### A. You changed the generator (`tools/gen_schedules.py`)

Adding a schedule, changing an existing schedule's actions, nodes or
options, changing the root seed. The corpus is *supposed* to change.

```
python tools/gen_schedules.py --lock            # rewrites schedules/*.json and MANIFEST
python tools/gen_schedules.py --check           # must now be green
python tools/reference_traces.py --check        # will report INPUT for the changed schedules
python tools/reference_traces.py                # rewrites traces/*.digest
python tools/reference_traces.py --check        # must now be green
```

`reference_traces.py --check` distinguishes an **INPUT** change (the
schedule digest moved: regenerate) from a **MISMATCH** (the schedule is the
same but the trace moved: see B or C). After step A only the schedules you
touched should have been reported as INPUT. If an untouched schedule shows
MISMATCH you have also made a behaviour change; go to B.

Never edit a file under `schedules/` by hand. The generator is the source;
`--check` compares disk against the generator byte for byte precisely so
that a hand edit is caught.

### B. You changed behaviour on purpose

A new rule, a changed rule, a new committed-visible event kind (for
example the `snapshot` and `snapshot_installed` events of `SPEC.md` 6.7).
The reference digests are *supposed* to change for the schedules the rule
affects.

1. Make sure the change is documented in the order `CONTRIBUTING.md`
   requires (ADR, spec, code, tests).
2. Run `python tools/reference_traces.py --check` and read the list of
   MISMATCH schedules. Each line gives the reference and actual digests and
   the event counts; for each mismatching schedule the tool prints the last
   digest events of the recomputed trace, with tick numbers.
3. For at least one affected schedule, look at *where* the first divergence
   is and confirm it is where your change should first show:

   ```
   git stash                                        # or check out the base commit elsewhere
   python tools/reference_traces.py --only long-haul --traces /tmp/base --write-traces /tmp/base
   git stash pop
   python tools/replay_trace.py schedules/long-haul.json --reference-trace /tmp/base/long-haul.jsonl
   ```

   `replay_trace.py` prints the first divergent committed-visible event from
   each side with its sequence number and tick. Write the tick into the
   change description. A divergence hundreds of ticks before the first
   place your rule could apply means you changed something else too.
4. Regenerate and verify:

   ```
   python tools/reference_traces.py
   python tools/reference_traces.py --check
   PYTHONPATH=src python -m pytest tests
   ```

5. Commit `traces/` together with the code and the documents, and say in
   the commit which schedules moved and why.

### C. You did not mean to change behaviour

A refactor, a performance change, a trace field rename. If
`reference_traces.py --check` is red, **do not regenerate**. The digest
covers only `commit`, `apply` and `violation` events (`SPEC.md` 8.4), so a
change that only touches message handling, heartbeat batching or network
bookkeeping leaves every digest alone. A red check after such a change
means one of:

* the refactor changed *when* something commits (a phase-order change in
  `Cluster.step()`, a changed sync point, a changed timer reset), or
* you changed the fields of a `commit` or `apply` event (field names and
  values are part of the digest; `seq` is not), or
* you introduced non-determinism (run the same schedule twice and compare:
  `python tools/replay_trace.py schedules/baseline-steady.json --save /tmp/a.jsonl`
  and again with `--reference-trace /tmp/a.jsonl --all`).

Find which, and fix the code. If the conclusion is that the behaviour
change is wanted after all, you are in situation B and the paperwork of B
applies.

## 2. Reading the tools' output

`tools/gen_schedules.py --check` prints one line per problem:

```
differs from generator: partition-minority.json (schedule digest 6fbfacfb8d314be7)
MANIFEST mismatch: leader-isolated.json recorded 6dabf30c6fd8b8fe actual 7d0ee557dd8f69bd
not in MANIFEST: my-new-schedule.json
in MANIFEST but not on disk: old-schedule.json
```

`tools/reference_traces.py --check` prints one line per schedule that
differs, prefixed `MISSING`, `INPUT` or `MISMATCH`, then a summary. With
`-v` it also prints `ok` lines with the short digest and the event count,
which is useful to paste into a change description.

`tools/replay_trace.py` prints the run's digest and, with a reference,
either `match` or the first divergence:

```
first divergence at position 412:
  reference: 0007731 t=002145 n3     commit           entry_term=3 how=majority index=58 previous=57 term=3
  actual:    0007744 t=002151 n3     commit           entry_term=3 how=majority index=58 previous=57 term=3
```

Here the same entry committed six ticks later: a timing change, not a
safety change. Whether that is acceptable is a question for the ADR that
motivated the change.

## 3. Flags

| Tool | Flag | Meaning |
| --- | --- | --- |
| `gen_schedules.py` | `--seed N` | root seed (default `20261110`); every schedule's seed is derived from it |
| | `--out DIR` | corpus directory (default `schedules/`) |
| | `--lock` | also write `MANIFEST` |
| | `--check` | compare disk with generator and MANIFEST; write nothing; exit 1 on difference |
| | `--list` | print the schedule summaries and exit |
| `reference_traces.py` | `--schedules DIR`, `--traces DIR` | where to read schedules / write digests |
| | `--check` | compare instead of writing; exit 1 on any difference |
| | `--only NAME` | restrict to one schedule (repeatable) |
| | `--write-traces DIR` | also write full JSONL traces (for later `replay_trace.py --reference-trace`) |
| | `-v` | print `ok` lines too |
| `replay_trace.py` | `--reference FILE` | a `.digest` file (default `traces/<name>.digest`) |
| | `--reference-trace FILE` | a full JSONL trace; enables first-divergence output |
| | `--all` | compare every event kind, not only digest kinds |
| | `--seed N`, `--ticks T` | overrides, as for `python -m tidewater run` |
| | `--save FILE` | write the new JSONL trace |
| | `--tail N` | how many digest events to print on a digest-only mismatch |

## 4. Timing

The full `reference_traces.py` run (or `--check`) takes roughly a minute:
twelve schedules, the longest 6000 ticks with five nodes and the invariant
monitor on every tick. `--only three-node-minority-crash` takes a few
seconds and is what the repository suite uses. Do not shorten schedules to
make the check faster; the long ones are long because the symptoms in
`docs/incidents/` took that long to appear.
