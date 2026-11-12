# The schedule file

A schedule is the whole of a run's input except the code: the node set, the
node and network options, the seed, the length in ticks, and the list of
faults with the tick each one fires at. Two runs of the same schedule on the
same code produce the same trace, and `traces/<name>.digest` is what that
trace is expected to look like. `src/tidewater/schedule.py` is the
implementation; this is the document an author reads first.

## The document

```json
{
  "schema": 1,
  "name": "partition-heal-storm",
  "description": "one paragraph of intent",
  "nodes": ["n1", "n2", "n3", "n4", "n5"],
  "seed": 499287,
  "ticks": 3020,
  "give_up_after": 0,
  "options": {"election_timeout": 50, "heartbeat_interval": 10, "pre_vote": true,
               "max_entries_per_append": 16, "compaction_threshold": 0,
               "sync_policy": "always"},
  "network": {"min_delay": 1, "max_delay": 3, "drop_rate": 0.0,
               "dup_rate": 0.0, "dup_extra_delay": 4},
  "actions": [ {"at": 300, "kind": "partition", "groups": [["n1","n2"],["n3","n4","n5"]]} ]
}
```

`nodes` is sorted, always: every iteration in the simulator is in that order,
and an unsorted list is a schedule error rather than a silent reordering.
`ticks` is the length; an action at or past `ticks` is an error at load time.

## The actions

| kind | arguments | what it does |
| :--- | :--- | :--- |
| `propose` | `command` (`op`, `key`, `value`, `expect`) | offered to whoever is leader at that tick, retried every tick until accepted or `give_up_after` |
| `workload` | `count`, `every`, `key_prefix`, `op`, `keys` | expands to `count` `propose` actions `every` ticks apart |
| `partition` | `groups` | only intra-group traffic survives, until a `heal` |
| `heal` | — | the links come back |
| `isolate` | `node` | one node reaches nobody and nobody reaches it |
| `block` / `unblock` | `src`, `dst`, `both` | one direction (default both) of one link |
| `crash` | `node` | the node is down; in-flight mail to it is dropped |
| `restart` | `node` | it comes back as a follower from durable state |
| `skew` | `node`, `rate`, `offset` | its clock runs `rate` ticks per global tick, `offset` ticks ahead |
| `network` | `min_delay`, `max_delay`, `drop_rate`, `dup_rate`, `dup_extra_delay` | changes the transport for the rest of the run |

Actions at the same tick fire in file order. Validation is strict and happens
at load: an unknown kind, a node that is not in the cluster, a `propose`
without a key, a `workload` that runs past the end of the schedule, a `skew`
with neither `rate` nor `offset`, all raise `ScheduleError`.

## Constraints an author has to respect

`max_delay * 2 < election_timeout`, or no leader can hold its followers: a
heartbeat has to be able to reach a follower and be answered before the
slowest timer fires. `heartbeat_interval * 3 <= election_timeout`, for the
same reason stated in `SPEC.md` 1.3.

## Two clocks, and which one the timers use

A node's election timer is compared against its **local** clock
(`offset + rate * global`). A `skew` action with `rate: 4` therefore fires
that node's timeouts roughly four times as often as everyone else's, which is
the scenario `clock-skew` exists for and the reason for the leader lease in
`ADR-0009`.

## Regenerating the corpus

```bash
python tools/reference_traces.py            # rewrite traces/*.digest
python tools/reference_traces.py --check    # exit 1 if any digest differs
python tools/gen_schedules.py --lock        # rewrite schedules/MANIFEST
python tools/gen_schedules.py --check       # exit 1 if disk differs from MANIFEST
```

A new schedule file is not part of the corpus until it is in `MANIFEST`, and
`MANIFEST` is written by the tool, not by hand.
