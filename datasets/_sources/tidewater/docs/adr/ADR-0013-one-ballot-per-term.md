# ADR-0013: One ballot per term — rivals, late answers, and tallies

Status: accepted. Supersedes nothing; refines `SPEC.md` 2.5 and 2.6, and is
the rule `docs/incidents/INC-0009` was closed with. Referenced by:
`Node._handle_request_vote`, `Node._start_election`,
`Node._handle_vote_response`.

## Context

`SPEC.md` 2.6 says a voter grants a real vote when `voted_for` is empty or
already the candidate. It does not say what "already" means for a node that
is not a follower, and the prototype read it as a rule about followers: the
`already_voted` test was reached only on the follower path, and a node that
was itself standing in the term answered whoever asked. `SPEC.md` 2.5 says a
candidate becomes leader when it "collects votes from a majority". It does
not say which answers are votes, and the prototype read the tally as a
running counter: whatever came in while the node was a candidate was added to
whatever was already in the set.

Both readings are harmless in a cluster that runs one election at a time.
They stop being harmless in the two cases every election has: two nodes that
timed out together, and an answer that arrives after the election it answers
has ended.

## Decision

1. **The ballot belongs to the term, not to the role.** A node holds at most
   one real ballot in a term and its own candidacy uses it. The check that
   `voted_for` is empty or already the candidate is made *before* any
   consideration of the node's role: a candidate, a pre-candidate and a
   follower all answer a `RequestVote` the same way, and a candidate that has
   voted for itself denies a rival with `already_voted`. Answering a rival
   with a grant is casting a second ballot in a term the node has already
   spent.
2. **A tally belongs to one election.** Starting an election creates the
   tally with the candidate alone in it. A tally does not survive the
   election that made it: the next term starts from one ballot — the
   candidate's own — because every answer collected so far was about a term
   that no longer exists. Carrying a tally over is crediting the new election
   with ballots that were cast against the old one.
3. **Only answers about this election are votes in it.** A `RequestVoteResponse`
   counts when the node is a candidate, the answer is a grant, and the term in
   the answer is the candidate's current term. An answer from a term that has
   closed is a late post about an election that failed: it is not a ballot,
   and it is not an obstacle either — a denial or an answer from a higher term
   is handled by 2.1, not added to the tally.
4. **A voter that cannot remember is a voter that did not vote.** The ballot
   is written and *synced* before the reply leaves (ADR-0012), and the sync
   is the whole record — term and vote together. A fix that restores a missing
   `sync()` without reading what `sync()` makes durable satisfies the call
   site and breaks the contract: the crash that follows undeclares the vote,
   which is the failure this decision exists to prevent.

## Consequences

* A candidate that denies every rival in its term is slower to converge and
  sometimes fails an election that nobody wins. That is correct: a failed
  election is cheap, a term with two leaders is not.
* The three rules are indistinguishable from the outside — all of them end in
  `election_safety`, `term N has two leaders: A and B` — so a run that shows
  the line must be read from both ends: who voted twice, and which term each
  answer was about. `INC-0009` is how to tell them apart.
* None of the three rules mentions which module is at fault, and that is
  deliberate. The tally, the grant, and the durable record are three different
  places; the invariant they protect is one.
