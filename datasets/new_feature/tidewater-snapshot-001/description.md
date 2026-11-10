# Give the cluster a way to stop remembering everything

Tidewater replicates and commits correctly, and its repository suite is green.
`SPEC.md` section 6 — snapshots and log compaction — is complete, normative,
and not implemented: every entry point of `tidewater.snapshot` raises
`FeatureNotImplemented`, the seed runs with `compaction_threshold = 0`, and the
log of a node that has been writing for an hour is the history of the cluster
byte for byte.

The feature this task asks for is the **node half** of section 6:

* when a node's log holds at least `compaction_threshold` entries and it has
  applied past its current boundary, it snapshots its state machine at
  `last_applied`, on its own, with no leader involved (6.1);
* the record is the state at that index — its canonical bytes, its term, and
  the configuration in force — and it is made durable **before** the log it
  justifies is compacted, so that a crash between the two leaves a longer log
  and a usable snapshot and never a shorter log and no snapshot (6.2);
* compaction keeps a suffix so that a follower which is slightly behind is
  still served by `AppendEntries`, never passes `last_applied`, and keeps the
  **term of the boundary** so that a prefix which ends exactly at the boundary
  still matches, on that term, as an entry would (6.3);
* a node that restarts holding a snapshot loads its state machine from the
  record, starts at `last_included_index`, and replays only the suffix, rather
  than rereading the history of the cluster as the seed does today (6.6, 5.4);
* taking a snapshot is an event of the trace and, being visible in what the
  cluster committed, it takes part in the digest (6.7).

Shipping that is also a corpus change, and the repository has a procedure for
that: `docs/runbooks/regenerate-traces.md`. A snapshot event in the digest is
exactly the kind of change the runbook exists for, and the incident about
reference digests changing after a harmless refactor explains what the
maintainers treat as a process failure. Add a schedule that exercises
compaction **through the generator**, lock it with
`tools/gen_schedules.py --lock`, record its reference digest with
`tools/reference_traces.py`, and leave both artefacts in the tree; a schedule
file written by hand, or a digest copied from a run without the tool, is not
this procedure.

`CONTRIBUTING.md` states the hierarchy of truth (`docs/adr/` over `SPEC.md`
over the module docstrings over `README.md`); the ADRs about the boundary term
and about resuming a transfer say why the boundary is a term and not just an
index. `README.md` claims compaction is already on by default — it is not, and
the README is approximate here by its own admission.

Do not implement the transfer of a snapshot to another node (`SPEC.md` 6.4,
6.5): that is the next task in this family and its entry points are expected to
keep raising. Two records of the repository describe this feature as a stub —
the declared-features test and the corpus size in the tools test — and both
move with the feature; leave everything else in the suite alone.

The hidden tests drive a node and a quiet five-node cluster, ask what a
snapshot record contains and when it became durable, what the log looks like on
both sides of the boundary, where a restarted node starts, what the trace and
the digest now say, and whether the new corpus entry was generated, locked and
digested by the tools. The public tests state the same needs as complaints.
