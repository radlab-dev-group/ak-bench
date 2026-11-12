---
id: INC-0004
severity: high
module: journal
tags: crash, lost-write, sealed-segment, torn-tail, ops
---

# INC-0004: the store that opened clean and was one transaction short

## What we saw

A reconciler host filled its data partition while a compaction was starting.
The worker was restarted, came back with no errors, and reported a sequence
number one lower than the one a client had been shown a minute earlier. The
transaction behind that number was not in `stats()`, was not in the WAL, and
was not mentioned anywhere in the log. The store accepted new work as if
nothing had happened.

The capture is under `docs/incidents/captures/INC-0004/`: the damaged segment,
the empty newest segment next to it, the directory listing, and the frame map
someone made of it. Every frame that survived has a correct checksum. The
segment ends 11 bytes into the middle of a frame.

## What it turned out to be

The damaged segment was sealed. Only the segment the journal appends to may end
in an incomplete frame, and the truncation that follows a torn tail is a repair
precisely because nothing outside that segment depends on the bytes. The
torn-tail allowance had been widened to every segment the journal opens, so the
restart read the sealed segment with the eyes of an append target, cut off the
last frame, and replayed what was left as though it were the whole history.

The repository suite never caught it because the suite only ever tears the
segment it is appending to. The capture is the first store anyone opened with a
damaged *sealed* segment in it.

## What we changed

The allowance lands on exactly one segment again, and the refusal path writes
nothing: a store that cannot be opened is a store that has not been modified.
See the decision record about which segment may be torn, and INC-0003 for the
other direction of the same rule — the allowance was once too narrow, and it
refused a store that should have opened.

## Read next

`ADR-0003` for the rule, `INC-0002` for acknowledged work that disappeared
during the same compaction window, and the capture's `crash_backtrace.txt` for
the `ENOSPC` that is real and is not the defect.
