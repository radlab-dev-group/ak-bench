# Four fifths of the run is spent proving the run is correct

Profile `baseline-steady` — 2000 ticks, five nodes, sixty writes — and the
answer is not where the protocol is:

| where | share of CPU |
| :--- | ---: |
| `InvariantMonitor.check` | ~82% |
| `RaftLog.at` / `Entry.summary`, almost all of it from the monitor | ~37% |
| `Storage._wrote` and `Storage.sync`, which `copy.deepcopy` the whole log | ~8% |

`InvariantMonitor.check_log_matching` walks every *pair* of live nodes, and for
each pair scans the shared range of their logs index by index — every tick,
including the ticks in which nothing arrived and no log changed. `check_state_machine_safety`
scans `first_index .. last_applied` for every node, every tick, over history
that cannot change once it is written. The monitor is right and it must stay on:
`docs/incidents/INC-0002` and `INC-0009` are exactly what it catches. It is
doing work it has already done.

## What to do

Make the cost of a tick proportional to what happened in it. The shape of the
answer, not the answer:

- the monitor remembers what it has already proven and looks again only where
  something changed — which logs moved, which node applied something new;
- the log stops rebuilding the same `Entry.summary()` a million times, and stops
  the same for a node whose log did not move;
- the durability seam stops copying the entire log to prove that one entry
  arrived — `ADR-0012` is about the *order* of the writes, not about their size.

Measure with the tool in the repository:

```bash
python tools/bench.py --schedule schedules/baseline-steady.json --json
```

`cpu_seconds` is `time.process_time()`, so it counts this process's CPU and not
whatever else the machine felt like doing, and `traced_bytes_peak` is the run's
own allocation peak. Both are what the hidden harness compares, and it compares
them against a pristine copy of the seed measured the same way — the target is a
ratio, so a slower machine does not make the task harder.

## What must not change

**The trace, byte for byte, on all twelve schedules.**

```bash
python tools/reference_traces.py --check   # exit 0, twelve times
python -m pytest tests/                    # green
```

That is the whole ballgame: `ADR-0001` fixes the order of the phases in a tick
precisely so that an optimisation cannot reorder cause and effect, and
`ADR-0010` fixes which events take part in a digest. A queue that pops two
events due at the same tick in the other order produces a plausible cluster and
a wrong digest; `docs/incidents/INC-0006` is a week lost to exactly that, and
`SPEC.md` 1.6 is the rule about node iteration order that most people break by
accident.

**The checks stay on.** A faster run that no longer notices two leaders is not
an optimisation. The hidden harness runs a cluster that violates safety and
requires the violation to still be reported, and `SPEC.md` 2.4, 2.7 and 4.1 are
the rules the monitor exists to catch breaking.
