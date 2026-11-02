# A worker with a stale epoch can take a live lease back

`LeaseBook.takeover` in `src/cadence/lease.py` is supposed to answer one
question: does the caller still hold the epoch this resource was granted with?
A worker that was cut off and comes back still believes it holds the resource,
and asks for it back by the epoch it was given.

The rule, as documented in the module:

- the epoch is the whole question — a request for an epoch the book no longer
  carries is **stale**, because somebody else was granted the resource while the
  caller was silent;
- granting a stale request would put two workers on the same work, so a stale
  epoch is refused with `LeaseHeld`, and the current holder keeps its lease and
  its validity;
- a refused takeover must change nothing: not the holder, not the epoch, not
  the deadline.

The repository's own suite is green on the pinned commit, because it only ever
asks a holder back by the epoch it still carries. The defect only shows up when
a request arrives for an epoch the book no longer holds — which is exactly the
request that a worker that lost the lease makes.
