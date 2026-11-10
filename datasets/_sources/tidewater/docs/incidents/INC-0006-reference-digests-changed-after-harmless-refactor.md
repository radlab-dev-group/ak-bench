# INC-0006: Every reference digest changed after a "harmless" refactor, and a real change hid behind it

Severity: process (a behaviour change shipped unreviewed). Schedules: all
twelve. Status: closed; rules in `SPEC.md` 8.4, 9.4,
`docs/runbooks/regenerate-traces.md`; decision ADR-0010.

## Symptom

A commit titled "tidy outbox draining" turned `tools/reference_traces.py
--check` red on all twelve schedules. The author ran
`tools/reference_traces.py` without `--check`, which rewrote all twelve
`.digest` files, and committed them with the message "regenerate traces".
The check was green. Two weeks later a different change to `long-haul`
was being investigated with `tools/replay_trace.py --reference-trace`
against a trace saved before the tidy, and the first divergence was not
where the new change could have put it:

```
first divergence at position 1187:
  reference: 0014203 t=003312 n4     commit           entry_term=4 how=majority index=176 previous=175 term=4
  actual:    0014366 t=003342 n4     commit           entry_term=4 how=majority index=176 previous=175 term=4
```

Index 176 had been committing thirty ticks later since the tidy. The tidy
had changed behaviour. Nobody had looked, because the digest had said
"everything changed" and "everything changed" was expected.

## What we found

Two things, one in the tool and one in the change.

**The digest was over the whole trace.** Every `send`, `deliver`, `drop`,
`timeout` and `vote` event was hashed. The tidy swapped the order of two
`send` events within a tick — a node now drained its outbox in insertion
order rather than grouped by destination. Same messages, same ticks,
different `seq` numbers from that point on. Every digest moved. A digest
that moves on a change like that is not an alarm, it is noise, and the
author treated it as noise.

**The tidy was not harmless.** In grouping messages by destination the old
code had also, as a side effect, sent a follower's catch-up append before
the heartbeat to the next peer. The tidy reversed that, the catch-up
append now left one phase later, and under `long-haul`'s 5% drop rate the
sequence of drops the network stream produced shifted by one message from
tick 3100 on. One commit moved by thirty ticks. Nothing unsafe; a real
change to what the corpus asserts, shipped as "regenerate traces".

## The rules

1. The digest covers committed-visible events only — `commit`, `apply`,
   `violation` — and excludes the sequence number (`SPEC.md` 8.4,
   ADR-0010). A refactor that does not change what commits when leaves
   every digest alone, so a red check means something.
2. Regenerating `traces/` is a documented procedure with three cases
   (`docs/runbooks/regenerate-traces.md`): generator changed, behaviour
   changed on purpose, behaviour changed by accident. Only the second
   regenerates, and it writes down which schedules moved and why.
3. `tools/reference_traces.py --check` tells INPUT changes (the schedule
   moved) from MISMATCH (the trace moved), and `tools/replay_trace.py
   --reference-trace` names the first divergent event. "The digest
   changed" is never the end of the diagnosis.
4. `CONTRIBUTING.md` names regenerate-to-green without an explanation as a
   process failure.

## How it was diagnosed

By accident, as noted. The lesson for the tooling: the information needed
to see the problem — the first divergent committed event with its tick —
was available in the trace all along and nobody had a tool that printed
it. `replay_trace.py --reference-trace` was written during this incident.
`reference_traces.py --write-traces` was added so that full reference
traces can be kept outside the repository for exactly this comparison.

## What changed

* `tidewater.trace.DIGEST_KINDS`, `Trace.digest_events`,
  `TraceEvent.digest_material` (no `seq`).
* `tools/replay_trace.py` with `--reference-trace` and `--all`.
* `tools/reference_traces.py` with INPUT/MISMATCH distinction,
  `--write-traces`, `-v`.
* `.digest` files record `events` and `digest_events` separately.
* The runbook, and the CONTRIBUTING paragraph.
* The tidy itself was kept (the new order is the documented one,
  `SPEC.md` 1.2 phase 5) and the thirty-tick shift was recorded as the
  reason the `long-haul` digest moved.

## What to check if you see this again

If `reference_traces.py --check` is red after a change you believe is
behaviour-neutral, do not run it without `--check`. Save a trace from the
base commit (`--write-traces`), run `replay_trace.py --reference-trace`
on the smallest red schedule, and read the first divergence. The tick it
names is where to start reading the two traces side by side.
