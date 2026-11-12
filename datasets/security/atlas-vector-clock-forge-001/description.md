# The lease moved sideways, and the fence said yes

Two workers, one key, one generation number. Worker A is cut off in the middle
of a write; worker B finishes, and the lease moves to B. A comes back, commits
the write it was still holding, and names the generation the lease already
carries. The take-over is granted. Nothing raises. The next ordinary write on
that key is then refused, and the person reading the lease cannot tell why,
because the lease no longer describes what anybody wrote.

This is a fencing-token bypass: the vulnerability is one comparison in the check
that exists to stop exactly this, and the fix has to be narrow enough that a
worker which really is ahead still gets the key.

## Where the contract is written

- `SPEC.md` §5.1 and `README.md` rule 4 — the generation check is an equality
  under `strict`, in both directions, and no incident note may relax it.
- `docs/adr/ADR-0003-a-version-is-minted-once.md` — the lease book "moves
  **forward only**. A holder offering a generation at or below the one on record
  is refused with the stale-generation error, whichever path it arrived by."
  The second symptom in that record is what you are being paid for.
- `docs/incidents/INC-1204-a-lease-that-walked-backwards.md` — this hole, once
  before, including what the fix has to leave alone: a replica that is behind is
  brought level by a read, not by a lease that lies for it.
- `docs/incidents/INC-1202-the-fence-refused-a-generation-nobody-wrote.md` — the
  opposite failure, which is the trap in this task.
- `src/atlas/fencing.py` — the module the two checks live in. Note that the
  write-path check deliberately ignores *who* is writing and looks only at the
  generation, which is why the generation bookkeeping is the only thing holding
  the door.

## What must stay true

1. A take-over at a generation **strictly ahead** of the record is granted, and
   the holder is recorded.
2. A key with no lease on record can be granted at any generation — including
   the generation a released lease used.
3. `generation_check: permissive` keeps meaning "a peer that is behind may
   write"; it does not mean the lease book accepts a sideways take-over.
4. Read-repair, anti-entropy and migration keep calling the paths they call
   today; `tools/check_arch.py` and the repository suite both have to stay green.

## Deliver

1. The fix, in the source.
2. A regression test in `tests/test_lease_take_over.py` that fails on the build
   you were given, passes on yours, and pins properties 1 and 2 so that the next
   person to "fix" INC-1202 does not reopen this one.
3. `python -m pytest tests/` green and `python tools/check_arch.py` green.
