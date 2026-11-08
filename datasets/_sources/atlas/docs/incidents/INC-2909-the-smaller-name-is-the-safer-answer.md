---
id: INC-2909
severity: medium
module: convergence
kind: an argument we lost
tags: protocol, tie-break
---

# INC-2909: the smaller name is the safer answer

There was an argument, made seriously and in detail, that the tie-break
should resolve to the *smaller* writer identifier: smaller names sort first,
they are what a merge that takes the first entry produces, and a cluster
whose writer names were assigned in the order the machines joined had, for
its first years, a smallest name that was also its oldest machine, so the
ascending answer and the oldest-writer answer agreed and nobody could tell
which one the rule was. The argument is preserved here because it is the
argument a review makes when it reads a flipped comparison and finds the
flipped direction defensible. It is also wrong on its own terms: the rule is
the greatest name, in one direction, and the era in which the two directions
agreed is over, which is precisely when the direction a rule points stops
being observable. If a deployment's names were assigned out of order, the
ascending answer is not a fallback, it is a fork.
