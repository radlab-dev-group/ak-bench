# Two leaders, and not one illegal ballot between them

A five-voter Tidewater cluster ends a run with

```
term 1 has two leaders: p and y
```

The runbook for that line says to read the ballots, and the ballots are
clean. Both candidates were candidates in term 1; every answer in both tallies
is a grant, in term 1, given to a node that was a candidate when it landed; no
machine granted twice; no machine restarted; nothing was late. And yet one of
the two tallies contains a machine that answered nobody in its life — in the
trace it has no `vote` event at all. The operators' note reads: "the ballots
are right and the names are wrong".

The repository suite is green and all twelve schedules of the corpus run
without a violation, because in the corpus an answer always arrives from the
machine that signed it. The scenario that does not appear there is an answer
that reaches a candidate *through* another machine — a link that forwards, an
answer that comes back by the way the request came, a proxy. That is not a
second vote; it is one vote with a different machine on the envelope.

`CONTRIBUTING.md` states the hierarchy of truth: the decision records under
`docs/adr/` outrank `SPEC.md`, which outranks `README.md`; the incident notes
are evidence, indexed by symptom. The symptom here — two leaders in one term —
is the symptom of `docs/incidents/INC-0002` and of `docs/incidents/INC-0009`,
and neither of those is this defect: read the incident that matches what the
ballots actually say, not the one that matches the violation you were handed.
The rule this run needs is the one about **which set a majority is counted
over**; it is stated in `SPEC.md` and listed, among its disguises, in the
incident about a majority of the wrong set.

The hidden tests hand a candidate a grant carried in another machine's
envelope, hand it the same grant twice, and then let the rival collect the two
real ballots that are left; they ask after each step whom the candidate is
counting and whether the safety monitor allows what happened. The public tests
are the operators' reports.

Keep the public API, the message types, the trace format, and the crash
contract intact. Do not edit the specification, the decision records, the
incident notes, or the repository suite to match the code, and do not
regenerate the reference digests.
