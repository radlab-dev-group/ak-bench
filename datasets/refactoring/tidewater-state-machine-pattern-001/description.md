# The role is a variable, and the code reads it six times

`Node` holds one field that decides almost everything — `self.role` — and the
code asks it in six places, each of which re-implements the term comparison
that guards it:

```python
if self.role == LEADER:
    if now >= self.heartbeat_due:
        ...
elif now >= self.election_deadline:
    ...
```

Granting a vote, accepting an `AppendEntries`, starting an election, counting
a quorum: every one of them is `if role ==` plus a copy of the rule from
`SPEC.md` 2.1 about a higher term winning. The copies drift. `ADR-0012` exists
because one of them did — persist before reply, in the leader's path and not in
the candidate's — and `docs/incidents/INC-0009` is the week two of them
disagreed about who was allowed to be leader.

## What to build

A role hierarchy under `src/tidewater/roles/`:

- `BaseRole` — what every role does the same way: adopting a higher term,
  stepping down, deciding whether a log is at least as up to date (2.6), the
  persistence order (5.x). One implementation, so there is one rule.
- `FollowerRole` — election timeouts, accepting replication.
- `PreCandidateRole` — pre-vote without touching persistent state (2.4).
- `CandidateRole` — the real election: bump the term, vote for yourself, count
  a majority (2.5).
- `LeaderRole` — heartbeats, `AppendEntries`, `next_index`/`match_index`,
  advancing the commit index (3.x, 4.1).

`Node` becomes the context: it owns the state, and `receive`, `tick` and
`propose` delegate to the role that is currently installed. The package
exports the four classes and a mapping named `ROLES` from the role name —
exactly the strings `tidewater.node` already uses, because they go into the
trace — to the class that implements it. Each role class implements at least
`on_tick` and `on_receive`, and they share one base class.

## What must not change

The trace is the specification. `SPEC.md` 1.1 says two runs produce the same
trace, and `traces/*.digest` is that trace for the twelve schedules in
`schedules/`:

```bash
python tools/reference_traces.py --check   # exit 0, twelve times
python -m pytest tests/                    # green
```

A message that leaves in a different order, a trace event recorded one tick
later, a role named differently in a trace field — all of them are a mismatch,
and a mismatch is the refactor having changed the behaviour it was supposed to
preserve. `docs/incidents/INC-0006` is what that looks like and how long it
took to find once.

Keep `tidewater.node.Node`, `NodeOptions` and the four role constants working
exactly as they are today: the cluster driver and the repository suite both use
them, and neither is yours to change.
