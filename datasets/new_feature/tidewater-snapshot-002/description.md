# The node that was away too long has nothing to catch up with

Compaction has landed. A node whose log reaches `compaction_threshold` takes a
record of its state machine at `last_applied`, compacts behind it, keeps the
term of the boundary, and comes back from the record instead of replaying the
history of the cluster. That is `SPEC.md` 6.1, 6.2, 6.3 and the restart half of
6.6, and it works.

It also created a new way to fail, and the storage team has filed it: a node
that is cut off while the rest of the cluster keeps writing wakes up after the
link heals to find that the entries it needs are **gone from its leader too**.
The leader tries to send an `AppendEntries` whose prefix the leader itself
compacted away, and there is nothing in the tree that can answer that. The
messages exist (`InstallSnapshot`, `InstallSnapshotResponse`), the data classes
exist (`SnapshotTransfer`, `PendingInstall`), `Node._send_snapshot`,
`Node._handle_install_snapshot` and `Node._handle_install_snapshot_response`
call into `tidewater.snapshot` — and the three functions they call still raise
`FeatureNotImplemented`, exactly as they did before compaction landed.

What the spec fixes, and what this task is:

* **the stream** (6.4) — the leader sends `data = state[offset, offset +
  chunk_size)`, one chunk outstanding, `done` on the chunk carrying the last
  byte; the leader continues from the offset the *follower* reports, whether
  that is forward or a rewind, because its own counter is the thing that got
  out of step in the first place;
* **the install** (6.5) — the follower buffers in volatile memory; a chunk that
  arrives out of order is answered with the offset it is actually waiting for
  and is otherwise ignored; on the last chunk it keeps the suffix after the
  boundary **only if it holds the boundary entry with the boundary term** and
  throws its log away otherwise, puts the boundary in `base_index`/`base_term`,
  makes the record and the log durable, and only then replies `done = True`;
* **the crash in the middle** (6.6) — the buffer is volatile, so a follower that
  restarts asks for `offset = 0` again, and the leader follows it;
* **the trace** (6.7) — a completed install is an event of its own, and, like
  the snapshot event before it, it is visible in what the cluster committed and
  therefore takes part in the digest.

That last point is a corpus change, and the repository already has a procedure
for those: `docs/runbooks/regenerate-traces.md`, the incident about reference
digests moving after a harmless refactor, and the ADR that says a transfer
resumes from the follower's offset rather than the leader's memory. Add a
scenario in which a node is cut off long enough that the cluster compacts away
what it needs and then heals, **through the generator**, lock it with
`tools/gen_schedules.py --lock`, record its reference digest with
`tools/reference_traces.py`, and leave both artefacts in the tree. A schedule
written by hand, a digest pasted from a run, or a scenario that never actually
separates a node past the boundary is not this procedure.

`CONTRIBUTING.md` gives the hierarchy of truth (`docs/adr/` over `SPEC.md` over
the module docstrings over `README.md`), and the README is still approximate
about all of section 6. Three records of the repository describe this surface as
a stub — the declared-features test, the digest-kind set, and the size of the
corpus — and all three move with the feature; leave everything else in the suite
alone.

The hidden tests drive one leader and one follower chunk by chunk and ask what
is on the wire, what a follower that was answered out of order replies, what
survives an install and what does not, what has to be durable before `done`,
what a crash in the middle costs, where the leader's books end up when the
transfer finishes, and whether the new corpus entry was generated, locked and
digested by the tools. The public tests state the same needs as complaints.
