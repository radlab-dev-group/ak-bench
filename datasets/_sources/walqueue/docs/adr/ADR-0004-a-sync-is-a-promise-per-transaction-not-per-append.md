# ADR-0004: a sync is a promise per transaction, not a syscall per append

Status: accepted. The README says the queue is durable: a transaction that
`put`, `reserve`, `ack` or `release` returns from has been written and synced.
It does not say what a caller is owed when several transactions are in flight,
and it is the difference between a queue that batches and a queue that loses.

## Context

`Journal.append` writes one frame and then `os.fsync`s it, which is correct and
costs a system call per transaction. The obvious optimisation — keep the bytes
in a buffer and sync when the buffer fills — is correct only if the buffer is
invisible to the caller, and it is not: a transaction that has returned is a
transaction the client has already told somebody else about.

The seam that makes the two compatible is the one the code already has. A
frame is written whole or not at all (`ADR-0003`: only the newest segment may
end in a torn frame, and a torn tail is truncated at recovery), and a
transaction is one frame. A buffer may therefore hold as many *complete* frames
as it likes, and it must hold no partial frame across a return.

## Decision

Batching is allowed, and these are the rules it must not cross:

* A call that returns success has had its frame synced. Buffering may move the
  sync earlier, never later — a group commit that syncs the frames written
  before it is legal, a buffer that returns first is not.
* A frame is never split across a buffer flush and never split across a
  segment; the length prefix, the payload and the digest of one frame leave
  together.
* A failed write leaves the journal exactly as it was. The offset the store
  believed in before the attempt is the offset it believes in after, and no
  bytes a later recovery would have to truncate are left behind.
* The checksum covers the same bytes it covers today. Optimising the path that
  computes them is welcome; changing what they cover is a format change.

## Consequences

A benchmark that measures append throughput must measure it with the durability
contract on, because a queue that never syncs is faster than any queue that
does and is not the same program. `tests/` keeps the crash matrix, and the
crash matrix is the acceptance test for every buffering scheme: whatever the
buffer, restarting after a failure at any of the hook points must recover the
same state.
