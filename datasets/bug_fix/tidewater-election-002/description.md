# A cluster that decides with half of itself

A four-voter Tidewater cluster misbehaves in two ways that look unrelated:

* it **elects a leader on two of four ballots**. The wall then shows
  `term N has two leaders: p and r`, one in each half of a cluster that had
  been partitioned in two equal halves, and neither half ever saw a majority
  of four by anyone's counting;
* on the same split it **reports entries committed on two of four replicas**:
  the leader's own copy plus one follower is enough for the leader to advance
  its commit index, and the client is told the write is durable while half the
  cluster has never heard of it.

The repository suite is green and all twelve schedules of the corpus run
without a violation. Every cluster in the corpus has an odd number of voters,
and so does every cluster in the suite.

This is the same invariant the other election reports in this family are
about — a decision belongs to a majority — and it is not the same code. The
rule is written once, in `SPEC.md`, and the incident note that reads most
like this symptom was written about a *minority side that kept committing*
during a partition, which is the other end of the same arithmetic.
`CONTRIBUTING.md` states the hierarchy: the decision records under `docs/adr/`
outrank `SPEC.md`, which outranks `README.md`, and the incident notes are
evidence indexed by symptom, so they are what a search by symptom finds. The
README's paragraph on membership is, by its own admission, approximate.

The hidden tests ask the quorum question for every configuration size the
contract defines, drive elections and commits in a four-voter cluster by hand,
and run two fault schedules: a cluster split 2 and 2, where nothing may be
decided, and the same cluster split 3 and 1, where exactly one leader must
rise. The public tests are the operators' reports about a four-machine cluster
and do not name a module.

Keep the public API, the message types, the trace format, and the crash
contract intact. Do not edit the specification, the decision records, the
incident notes, or the repository suite to match the code, and do not
regenerate the reference digests.
