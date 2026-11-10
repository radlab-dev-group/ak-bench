# Restore the ballot rules of a cluster that elects two leaders

Tidewater is a deterministic, standard-library-only Raft-lite simulator. Its
repository suite is green and all twelve schedules of the corpus run without a
violation. The cluster still reports the same safety line over and over, in
orders the suite does not reach:

* `term 1 has two leaders: x and y`, where both leaders were elected on
  ballots that include the **same voter**, and nothing ever crashed;
* the same line, where the voter that appears twice **restarted** between its
  two ballots and its second reply said `granted=True`;
* the same line, where the second leader was elected in a term that began
  after the answer it counted was written;
* the same line again, where a candidate that failed an election two terms
  earlier won a later one with a single fresh ballot — and a leader of that
  later term existed at the same moment.

Every one of these is a different defect and all of them are one missing
rule. They arrive in two pairs and a single, and the pairs are the point: for
each pair, the change that makes the first symptom go away leaves the second
raising the identical `election_safety` line a scenario later, and the change
that makes the second go away brings the first back. That is what the
operators did for an afternoon, and it is why the trace of a run that ends in
this violation has to be read from both ends — who voted twice, and which
term each answer was about.

`CONTRIBUTING.md` states the hierarchy of truth: the decision records under
`docs/adr/` outrank `SPEC.md`, which outranks `README.md`, and the notes under
`docs/incidents/` are evidence written *by symptom* — they are indexed by what
the failure looked like, not by the module that was at fault, and two of them
discuss modules that turned out to be innocent. `SPEC.md` 2.5 and 2.6 say what
a node does; the rule that decides these five cases is in one record, and it
is written about ballots and terms rather than about functions, so searching
for a function name does not find it. `README.md` is, by its own admission,
approximate about elections.

The hidden tests drive nodes and small clusters by hand — rivals in one term,
an answer held back until its election failed, a voter that dies between
granting and remembering, an election that starts with the ballots of the one
before — and ask the safety monitor after each scenario whether what happened
is allowed. They also run the corpus, where a digest produced early in a
session has to still be the same digest at the end of it. The public tests
state the complaints the way the operators phrased them and give no
localisation.

Keep the public API, the message types, the trace format, and the crash
contract intact. Do not edit the specification, the decision records, the
incident notes, or the repository suite to match the code, and do not
regenerate the reference digests: nothing here is allowed to change what is
committed where and when.
