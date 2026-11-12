# The evidence is 16,000 lines of JSONL and there is no stack trace

`docs/incidents/INC-0010-a-node-that-stopped-taking-part-in-elections-after-tick-1200.md` is what the operators filed. The run finished
cleanly — no `violation` event, nothing pending — and yet a cluster with a
healthy majority took far too long to elect a leader after tick 1200. The trace
is 2.5 MB, which is more than anybody can read, and the simulator does not crash,
so there is nothing to catch.

This is a triangulation job: narrow 16,000 events down to the one tick where a
node started breaking a rule, and then fix the rule rather than the symptom.

```bash
gunzip -c docs/incidents/captures/INC-0010/incident_trace.jsonl.gz | head -3
gunzip -c docs/incidents/captures/INC-0010/incident_trace.jsonl.gz | grep -c '"node":"n3"'
gunzip -c docs/incidents/captures/INC-0010/incident_trace.jsonl.gz | grep '"kind":"skew"'
```

Those three commands are the shape of the search, not the answer. `jq` helps; so
does `tools/replay_trace.py`, which re-runs a schedule against a reference trace
and prints the first divergent event.

## The rules the trace is breaking

Read them before you touch code — the defect is a disagreement between what the
code does and what these say it does, and one of them is stated in the docstring
of the very function at fault:

- `SPEC.md` 2.3 — the election timer is `local_now + timeout`, drawn afresh at
  every reset, and reset at the events the section names;
- `ADR-0002` — what a node clock is: `offset + rate * global`, and what changing
  a skew is allowed to do to a clock that has already been counting;
- `SPEC.md` 2.4 / 2.7 and `ADR-0009` — pre-vote and the leader lease, which is
  the mechanism the operators checked and which is *not* what is wrong here.

`docs/incidents/INC-0007` is the earlier incident about a fast clock, and the
distinction between "a clock that runs fast" and "a clock that is moved" is the
thing the fix has to keep straight: a `skew` action must still be able to make a
node's clock run at `rate` and to declare an `offset`, without the node losing
the time it has already counted.

## Deliver

1. The fix, in the source.
2. A regression test in `tests/test_incident_reproduction.py` — under 100 ticks
   and under two seconds — that fails on the build you were given and passes on
   yours, and that also pins the case that must keep working: a `skew` action
   still declares an `offset` and still sets a `rate`.
3. The repository suite green (`python -m pytest tests/`) and the twelve
   reference digests still matching
   (`python tools/reference_traces.py --check`).
