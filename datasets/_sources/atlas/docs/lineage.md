# Lineage: why the graph looks like this

`SPEC.md` section 9 is the contract. This is the reasoning, for whoever has to
maintain the implementation and wants to know why the rules are shaped the way
they are.

## Why edges and not versions

A version says what a key holds. An edge says why, and "why" is the only thing
an operator asks at 3 a.m. The same version can arrive by three causes — a
write, a repair, a migration — and the answer to "should this value be here"
depends on which of the three it was. A store that records only versions can
tell you what changed; a store that records causes can tell you who is wrong.

## Why exactly five kinds

Six kinds is a design smell and the fifth already strains: `restored_by` is
not a cause the cluster created, it is the cluster admitting that it rebuilt
state from a log. The set is closed on purpose. A cause none of the five names
is a cause the recorder cannot explain to anyone, and an unexplainable edge in
a graph that exists to explain things is worse than a missing one.

## Why idempotence is spelled out

Recovery replays. Repair re-repairs. A migration resumes from a checkpoint and
copies a record it may have copied before. Every one of those paths can present
the same edge twice, and a graph that grows an edge every time a fact is
restated is a graph where "how many causes" stops meaning anything. So an edge
is its endpoints and its kind, and adding it twice is `False`.

## Why the observer may not participate

Lineage reads nothing. The store tells it what happened. The alternative — a
recorder that queries storage to fill in what it needs — means a lineage bug
can change what the store reads, and then a feature that is supposed to be
diagnostic has become a dependency of the path it diagnoses. The store already
knows the facts at the moment they are true; handing them over is cheaper in
every sense.

## Why the cap does not evict

A bounded graph that silently evicts its oldest edges produces a trace that
stops short and looks complete. That is the one output of a provenance system
that is actively dangerous: a plausible, truncated explanation. So the
recorder stops recording, returns `None`, and stays honest. Raise the cap if
the workload needs more history; do not make the graph lie to fit it.
