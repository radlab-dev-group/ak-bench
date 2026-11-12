# Nothing is wrong with this store, and it lost a transaction

`docs/incidents/INC-0004-the-store-that-was-one-transaction-short.md` is the
ticket; `docs/incidents/captures/INC-0004/frame_map.txt` says where the bytes
stop. The store on that host opens, accepts work, compacts, and logs nothing. It
is one transaction lighter than the number the client was shown.

This is a triage job, not a grep job: the damage is real, the code that let it
through is a single argument, and the tempting fix — refuse anything that is not
a complete frame — breaks the case the README promises to keep.

## Read these first

- `README.md` — the two sentences this whole thing turns on: an incomplete final
  frame in the newest segment is a recoverable torn tail; an incomplete frame
  anywhere else is corruption.
- `docs/adr/ADR-0003-only-the-newest-segment-may-end-in-a-torn-frame.md` — why
  the allowance must land on exactly one segment, and what the two failure
  directions look like. One of them is this ticket.
- `docs/incidents/INC-0003-…md` and `docs/incidents/INC-0002-…md` — the store
  that refused what it should have accepted, and the store that ate acknowledged
  work with no error. Read them as the two halves of one rule.
- `src/walqueue/codec.py` — `decode(..., allow_torn_tail=…)` is where the
  allowance is spent; `src/walqueue/journal.py` is where it is granted.

## What the capture actually shows

```bash
python -c "
from walqueue.codec import decode
d = open('docs/incidents/captures/INC-0004/corrupted_segment.wal','rb').read()
print(len(d), decode(d, allow_torn_tail=True))"
```

That command is the bug report in one line: a segment that was sealed reads as
`torn=True`. Now build the store the capture came from rather than the frame —
the `hook` argument of `Queue` is the crash-injection point the repository suite
uses, and `compact()` has a documented window, named in `ADR-0002`, where two
segments coexist and the older one is already sealed.

## Deliver

1. The fix, in the source.
2. A regression test in `tests/test_incident_regression.py` that fails on the
   build you were given and passes on yours, and that also pins the case that
   must keep working: a torn tail in the segment the journal appends to is
   truncated once, silently, and a second restart sees a clean store.
3. The repository suite green: `python -m pytest tests/`.
