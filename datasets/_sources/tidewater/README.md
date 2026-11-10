# Tidewater

Tidewater is a deterministic discrete-event simulator of a replicated log —
a small Raft: elections, log replication, a key-value state machine, crash
and network faults — with every safety property checked after every tick.
It is a benchmark seed: standard library only, no threads, no timers, no
sleeps, and no randomness except through seeded per-node streams, so a run
is reproducible byte for byte from a schedule file and a seed.

`SPEC.md` is the normative contract. This README is the map. Where the two
disagree, `SPEC.md` is right; where `SPEC.md` and a decision record under
`docs/adr/` disagree, the decision record is right (see `CONTRIBUTING.md`).

```
PYTHONPATH=src python -m pytest tests                          # the repository suite
PYTHONPATH=src python -m tidewater run schedules/long-haul.json --trace out.jsonl
PYTHONPATH=src python -m tidewater describe schedules/partition-heal-storm.json --expand
python tools/gen_schedules.py --check                          # corpus matches generator + MANIFEST
python tools/reference_traces.py --check                       # digests match traces/
python tools/replay_trace.py schedules/clock-skew.json         # re-run and compare
```

## What is here

| Module | Owns |
| --- | --- |
| `tidewater.clock` | the global tick, per-node skewed clocks, the event queue |
| `tidewater.rng` | the seed tree; one `random.Random` stream per node and one for the network |
| `tidewater.messages` | `RequestVote`, `AppendEntries`, `InstallSnapshot`, their responses, `TimeoutNow` |
| `tidewater.log` | entries, the log-matching check, truncate-on-conflict, conflict hints |
| `tidewater.statemachine` | the applied key-value map and its digest |
| `tidewater.storage` | persistent state per node with a durability seam for crash tests |
| `tidewater.node` | follower / pre-candidate / candidate / leader; the rules of `SPEC.md` 2–5 |
| `tidewater.network` | delays, drops, duplicates, partitions, blocked links |
| `tidewater.schedule` | JSON fault schedules and their validation |
| `tidewater.cluster` | the step loop: actions, proposals, deliveries, ticks, sends, invariants |
| `tidewater.invariants` | the six safety checks and `SafetyViolation` |
| `tidewater.trace` | the append-only trace, text/JSONL rendering, the digest |
| `tidewater.snapshot` | snapshots and compaction — **declared, not implemented** |
| `tidewater.membership` | `Configuration`; joint consensus — **declared, not implemented** |
| `tidewater.cli` | `python -m tidewater run | describe | digest` |

```
schedules/     twelve generated fault schedules and their MANIFEST
traces/        one .digest per schedule: the reference trace digest
tools/         gen_schedules.py, reference_traces.py, replay_trace.py
docs/adr/      decision records (the top of the hierarchy of truth)
docs/incidents/ what went wrong, written by symptom
docs/runbooks/ the regeneration procedure
docs/glossary.md
```

## How a run works

A schedule names the nodes, the seed, the length in ticks and a list of
actions (`partition`, `heal`, `crash`, `restart`, `skew`, `network`,
`propose`, `workload`). `Cluster.step()` fires the actions due at the
current tick, offers pending client commands to the leader, delivers the
messages that are due, ticks every node, drains every outbox into the
network, and runs the invariant monitor. Every one of those is a trace
event, and a long schedule produces tens of thousands of them; the
**digest** — a hash over the committed-visible events only — is the short
name of a run, and `traces/*.digest` are the reference digests the tools
check against.

## Elections in one paragraph

A follower that hears nothing from a leader for its election timeout starts
a **pre-vote**: it asks peers whether they would vote for it in the next
term without changing its own term. Only if a majority says yes does it
increment its term and run a real election. The timeout is randomised per
node: each node draws `T + jitter` with `jitter` uniform in `[0, T/2]`, so
two nodes rarely time out together and the quickest one usually wins. A
node that has recently heard from a leader denies pre-votes, which is what
stops a node with a fast clock or a healed partition from deposing a
working leader.

## Replication and commit in one paragraph

The leader sends `AppendEntries` with the index and term of the entry
preceding the new ones; a follower accepts only if it holds that entry, and
otherwise answers with a hint that lets the leader back up a whole term at
a time. A follower that already holds entries past the prefix keeps them
unless one of them conflicts in term, in which case it truncates from the
conflict. The leader commits an index once a majority of the configuration
holds it and the entry at that index is from the leader's own term; earlier
entries commit along with it. Followers learn the commit index from the
next append and apply up to it.

## Snapshots and compaction

Compaction is on by default: once a node's log passes the compaction
threshold (1,000 entries unless the schedule says otherwise) it snapshots
its state machine, drops the prefix, and ships the snapshot to followers
that fell too far behind in `InstallSnapshot` chunks. The boundary term is
kept so log matching at the boundary keeps working. See `SPEC.md` section 6
and `tidewater.snapshot`.

## Membership

The seed runs with a fixed configuration — the node list of the schedule.
Majorities are always counted over the configuration, never over whoever
answered. Joint consensus (`C_old,new`) is specified in `SPEC.md` section 7
and declared in `tidewater.membership`.

## Safety

Six invariants are checked every tick: `election_safety`, `log_matching`,
`leader_completeness`, `state_machine_safety`, `commit_regression`,
`membership_split`. A violation is a `SafetyViolation(kind, detail, tick)`,
is recorded as a `violation` trace event, and ends the run with exit status
2 from the CLI. The kinds are a closed set.

## Reading a trace

```
0001065 t=000369 n1     leader           commit=11 last_index=12 noop_index=12 term=2
0001502 t=000608 n4     step_down        leader='' reason=append_response term=2 was=leader
0001515 t=000610 n4     truncate         last_index=12 removed=10 term=2
```

Sequence number, tick, node (`-` for the network or the cluster), kind,
fields sorted by name. `python -m tidewater run ... --text` streams it;
`--trace out.jsonl` writes the machine form; `python -m tidewater digest
out.jsonl` prints the digest of a saved trace. When a reference digest
disagrees with a run, `tools/replay_trace.py --reference-trace` names the
first divergent committed-visible event with its tick.
