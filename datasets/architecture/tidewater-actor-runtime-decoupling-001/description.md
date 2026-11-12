# The node does four things at once and calls them a step

Read `Node._handle_append_entries` and count the collaborators it reaches for:
`self.storage` to persist, `self.log` to truncate, `self.trace` to record,
`self.outbox` to reply. Four, in an order that `SPEC.md` 5 says is load-bearing
— persist before reply, `ADR-0012` — and that order exists only because six
call sites happen to write their statements in the right sequence.

`docs/incidents/INC-0002` is what happens when one of them does not: two
leaders in one term, and the trace was the only witness. The fix was to move a
line. It should not have been possible to write it wrong.

## What to build

A node that computes, and a shell that acts.

**`src/tidewater/effects.py`** — the data. Two closed sets:

- *events*, the node's three inputs, each one a frozen dataclass: `Tick(tick)`,
  `Delivered(src, message)`, `Proposed(command)`;
- *effects*, what the node wanted to happen, each one a frozen dataclass
  deriving from a common `Effect` base: at least a send to a peer, a write to
  persistent storage, a trace record, a timer set, a role change and an applied
  entry. `effects.EVENTS` and `effects.EFFECTS` name the members of the two sets.

**`Node.step(event)`** — the function. It returns `(state, effects)`: the node's
state after the event and the list of effects it wants, in the order they must
happen. It does not append to `self.outbox`, does not call `self.trace.record`,
does not call `self.storage`. `tick`, `receive` and `propose` stay — the
cluster driver calls them — and become the thin wrappers over `step` that keep
the traces identical.

**`src/tidewater/runtime/actor_runner.py`** — the shell. `ActorRunner(trace)`
carries out the effects against a node with `apply(node, effects)`: fills the
outbox, writes to storage, records the trace, sets the timers, applies the
entries. It is the only place in the package that acts, and `step` is the only
place that decides.

The test for the split is not a look, it is an equivalence: interpret a node's
effects with your own shell and the node must end up in the same place, with the
same outbox and the same trace, as it reaches by calling `tick` and `receive`.

## What must not change

The trace is the specification. `SPEC.md` 1.1: the same schedule and seed
produce the same trace, and `traces/*.digest` is that trace for the twelve
schedules in `schedules/`.

```bash
python tools/reference_traces.py --check   # exit 0, twelve times
python -m pytest tests/                    # green
```

An effect emitted one place later than the call it replaces moves a trace event
and fails a digest. `ADR-0012` states the persistence order the effect list has
to make explicit; `ADR-0010` states which events take part in a digest, and
`docs/incidents/INC-0006` is what it costs to find out by accident.
